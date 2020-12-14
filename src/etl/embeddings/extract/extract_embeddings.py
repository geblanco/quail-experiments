import os
import sys
import json
import glob
import torch
import pickle
import argparse
import numpy as np

from tqdm import tqdm
from shutil import rmtree
from pathlib import Path

from transformers import is_tf_available, Trainer
from mc_transformers.utils_mc import MultipleChoiceDataset, Split
from mc_transformers.data_classes import DataCollatorWithIds
from mc_transformers.mc_transformers import (
    compute_metrics,
    setup,
    softmax
)

base_path = os.path.dirname(os.path.dirname(__file__))
sys.path.append(os.path.join(base_path, "transform"))
sys.path.append(os.path.join(base_path, "classify"))

from synthetic_embeddings import generate_synthetic_data  # noqa: E402
from dataset import save_data  # noqa: E402
from dataset import get_dataset as load_data  # noqa: E402
from dataset_class import Dataset  # noqa: E402


if is_tf_available():
    # Force no unnecessary allocation
    import tensorflow as tf
    gpus = tf.config.experimental.list_physical_devices("GPU")
    for gpu in gpus:
        tf.config.experimental.set_memory_growth(gpu, True)


os.environ.update(**{"WANDB_DISABLED": "true"})


def parse_flags():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s", "--split", required=False, default="dev", type=str,
        choices=["train", "dev", "test"],
        help="The split of the dataset to extract embeddings from"
    )
    parser.add_argument(
        "-a", "--args_file", required=True, type=str,
        help="Arguments in json used to work with the model"
    )
    parser.add_argument(
        "-x", "--extract", required=False, default=None, type=str,
        help="Field to extract from the json args file"
    )
    parser.add_argument(
        "-g", "--gpu", required=False, default=0, type=int,
        help="GPU to use (default to 0)"
    )
    parser.add_argument(
        "-o", "--output_dir", required=False, type=str,
        help="Output directory to store predictions and embeddings"
    )
    parser.add_argument(
        "--single_items", action="store_true",
        help="Whether to store the embeddings and logits as separate files"
    )
    parser.add_argument(
        "-p", "--pool", action="store_true",
        help="Whether to apply max pooling to the last layer of embeddings"
    )
    parser.add_argument(
        "--scatter_dataset", action="store_true",
        help="Whether to store the dataset scattered across multiple files or "
        "in a single file"
    )
    parser.add_argument(
        "-O", "--oversample", required=False, default=None, type=float,
        help="Synthetize data until proportions are met, only "
        "possible when imbalanced class is `incorrect` (e.g.: 0.5)"
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def mc_setup(args_file, extract, split):
    if extract is not None:
        args_file = json.load(open(args_file, 'r'))[extract]
    else:
        args_file = [args_file]

    config_kwargs = {
        "return_dict": True,
        "output_hidden_states": True,
    }
    all_args, processor, config, tokenizer, model = setup(
        args_file, config_kwargs=config_kwargs
    )
    model_args, data_args, dir_args, training_args, window_args = (
        all_args.values()
    )
    data_collator = DataCollatorWithIds()
    eval_dataset = get_dataset(data_args, tokenizer, split)
    trainer = Trainer(
        model=model,
        args=training_args,
        eval_dataset=eval_dataset,
        compute_metrics=compute_metrics,
        data_collator=data_collator.collate,
    )
    return all_args, model, tokenizer, trainer, eval_dataset


def prepare_inputs(inputs, device):
    for k, v in inputs.items():
        if isinstance(v, torch.Tensor):
            inputs[k] = v.to(device)
    return inputs


def get_model_results(logits, labels):
    preds = np.argmax(softmax(logits, axis=1), axis=1)
    return (preds == labels)


def gather_embeddings(embedding_path, embedding_cursor):
    embeddings = None
    embedding_files = glob.glob(f"{embedding_path}/*_data.pkl")
    embedding_files.sort()
    assert(len(embedding_files) == embedding_cursor)
    for emb_file in tqdm(embedding_files, desc="Merging"):
        with open(emb_file, "rb") as fin:
            new_embeddings = pickle.load(fin)["embeddings"]
            if embeddings is None:
                embeddings = np.array(new_embeddings)
            else:
                embeddings = np.vstack([embeddings, new_embeddings])
        os.remove(emb_file)

    return embeddings


def embed_dataset(model, dataloader, device, pool, output_dir):
    embeddings = None
    embedding_cursor = 0
    embedding_path = os.path.join(output_dir, "embeddings")
    logits = None
    labels = None

    max_pooling = torch.nn.MaxPool1d(model.config.hidden_size)
    model = model.to(device)

    for inputs in tqdm(dataloader, desc="Embedding"):
        inputs = prepare_inputs(inputs, device)
        with torch.no_grad():
            output = model(**inputs)
            last_hidden_state = output.hidden_states[-1]
            pooled_output = (
                max_pooling(last_hidden_state)
                if pool
                else last_hidden_state
            )
            numpyfied_logits = output.logits.cpu().numpy()
            numpyfied_output = pooled_output.cpu().numpy()
            numpyfied_labels = None

            if "labels" in inputs:
                numpyfied_labels = inputs["labels"].cpu().numpy()

            if logits is None:
                logits = np.array(numpyfied_logits)
                if numpyfied_labels is not None:
                    labels = np.array(numpyfied_labels)
            else:
                logits = np.vstack([logits, numpyfied_logits])
                if numpyfied_labels is not None:
                    labels = np.hstack([labels, numpyfied_labels])

            if embeddings is None:
                embeddings = np.array(numpyfied_output)
                if not pool:
                    embedding_cursor_str = str(embedding_cursor)
                    # Up to 9999 embedding files
                    prepend = "0" * (4 - len(embedding_cursor_str))
                    embedding_cursor_str = f"{prepend}{embedding_cursor_str}"

                    save_data(
                        embedding_path,
                        embedding_cursor_str,
                        embeddings=embeddings
                    )
                    embeddings = None
                    embedding_cursor += 1
            else:
                embeddings = np.vstack([embeddings, numpyfied_output])

    if not pool and embeddings is None:
        embeddings = gather_embeddings(embedding_path, embedding_cursor)

    return embeddings, logits, labels


def scatter_embed_dataset(model, dataloader, device, pool, output_dir):
    embedding_path = os.path.join(output_dir, "embeddings")
    max_pooling = torch.nn.MaxPool1d(model.config.hidden_size)
    model = model.to(device)

    embedding_cursor = 0
    num_choices = None
    labels = None
    for inputs in tqdm(dataloader, desc="Embedding"):
        inputs = prepare_inputs(inputs, device)
        with torch.no_grad():
            output = model(**inputs)
            last_hidden_state = output.hidden_states[-1]
            pooled_output = (
                max_pooling(last_hidden_state)
                if pool
                else last_hidden_state
            )
            numpyfied_logits = output.logits.cpu().numpy()
            numpyfied_output = pooled_output.cpu().numpy()
            if num_choices is None:
                out_shape = (
                    dataloader.batch_size, -1, *numpyfied_output.shape[1:]
                )
            else:
                out_shape = (-1, num_choices, *numpyfied_output.shape[1:])

            numpyfied_output = numpyfied_output.reshape(out_shape)
            numpyfied_labels = None

            if num_choices is None:
                num_choices = numpyfied_output.shape[1]

            if "labels" in inputs:
                numpyfied_labels = inputs["labels"].cpu().numpy()
                if labels is None:
                    labels = np.array(numpyfied_labels)
                else:
                    labels = np.hstack([labels, numpyfied_labels])

            for idx in range(len(numpyfied_output)):
                fname = str(embedding_cursor + idx)
                fname = "0" * (6 - len(fname)) + fname
                save_data(
                    embedding_path,
                    fname,
                    embeddings=numpyfied_output[idx],
                    logits=numpyfied_logits[idx],
                )

            embedding_cursor += len(numpyfied_output)

    return embedding_path, labels, embedding_cursor - 1


def embed_from_dataloader(
    dataloader, device, model, pool, scatter_dataset, synthetic, output_dir
):
    if scatter_dataset:
        embedding_path, labels, nof_samples = scatter_embed_dataset(
            model, dataloader, device, pool, output_dir
        )
        if synthetic or labels is None:
            synth_labels = np.zeros(shape=(nof_samples + 1))
        else:
            synth_labels = None

        Dataset.build_index(
            embedding_path,
            labels if synth_labels is None else synth_labels
        )
        dataset = Dataset(data_path=embedding_path)

        if synth_labels is None:
            logits = []
            for sample in dataset.iter_features():
                logits.append(sample["logits"])

            pred_labels_correct = get_model_results(np.array(logits), labels)
            pred_labels_correct = np.array([
                int(p) for p in pred_labels_correct.tolist()
            ])
            dataset.set_labels(pred_labels_correct)

        return dataset
    else:
        embeddings, logits, labels = embed_dataset(
            model, dataloader, device, pool, output_dir
        )

        # labels should not be null
        num_samples = logits.shape[0]
        num_choices = logits.shape[1]
        embeddings = embeddings.reshape(
            num_samples, num_choices, *embeddings.shape[1:]
        )

        if labels is not None:
            pred_labels_correct = get_model_results(logits, labels).tolist()
            # 1 Correct / 0 Incorrect
            pred_labels_correct = np.array([
                int(p) for p in pred_labels_correct
            ])
        else:
            # No information about correct samples,
            # synthetic data, set incorrect
            pred_labels_correct = np.zeros(shape=logits.shape)

        return dict(
            embeddings=embeddings,
            labels=pred_labels_correct,
            logits=logits,
        )


def get_num_samples(data, proportions, scatter_dataset):
    if scatter_dataset:
        data.ret_x = False
        data.ret_y = True
        labels = np.array([y for y in data])
    else:
        labels = data["labels"]
    total_samples = len(labels)
    current_samples = len(labels[labels == 0])
    if proportions > 1.0:
        proportions /= 100
    target_num_samples = round(total_samples * proportions)
    needed_samples = target_num_samples - current_samples
    if needed_samples < 0:
        raise ValueError(
            "Requested downsampling. \nCurrent samples for class 0 = "
            f"{current_samples}.\nRequested {target_num_samples}"
        )

    return needed_samples


def get_dataset(data_args, tokenizer, split, **kwargs):
    args = dict(
        data_dir=data_args.data_dir,
        tokenizer=tokenizer,
        task=data_args.task_name,
        max_seq_length=data_args.max_seq_length,
        overwrite_cache=data_args.overwrite_cache,
        mode=Split(split),
        enable_windowing=False,
    )
    args.update(**kwargs)
    return MultipleChoiceDataset(**args)


def oversampling(data_args, num_samples, tokenizer, split, output_dir):
    # ToDo :=
    #  - Add path to be able to import synthetic_embeddings
    #  - Generate embeddings
    #  - Save them
    #  - Create dataloader with new embeddings
    #  - Embed dataset
    output_dir = os.path.join(output_dir, "oversample_embeddings")
    synthetic_dir = generate_synthetic_data(
        data_args.data_dir,
        output_dir,
        num_samples,
        split,
        task=data_args.task_name,
        log=True
    )

    return output_dir, synthetic_dir


def merge_embedded_data(data_src, data_extra):
    for key in data_src.keys():
        if key not in data_extra:
            raise ValueError(
                f"Extra data lacks a key: {key}"
            )
        if len(data_src[key].shape) == 1:
            data_src[key] = np.hstack([data_src[key], data_extra[key]])
        else:
            data_src[key] = np.vstack([data_src[key], data_extra[key]])

    return data_src


def main(
    args_file,
    extract,
    split,
    output_dir,
    gpu,
    single_items,
    pool,
    scatter_dataset,
    oversample,
    overwrite,
):
    all_args, model, tokenizer, trainer, eval_dataset = mc_setup(
        args_file, extract, split
    )
    _, data_args, _, _, _ = all_args.values()
    device = torch.device("cuda", index=gpu)

    if scatter_dataset:
        dataset_file = os.path.join(output_dir, "embeddings", "index.csv")
    else:
        dataset_file = os.path.join(output_dir, f"{split}_data.pkl")

    embedded = None
    if overwrite or not Path(dataset_file).exists():
        eval_dataloader = trainer.get_eval_dataloader(eval_dataset)
        embedded = embed_from_dataloader(
            eval_dataloader,
            device,
            model,
            pool,
            scatter_dataset,
            synthetic=False,
            output_dir=output_dir,
        )
        if not scatter_dataset:
            save_data(output_dir, split, single_items, **embedded)

    if oversample is not None:
        oversample_rate = str(oversample).replace('.', '')
        oversampled_name = f"{split}_oversample_{oversample_rate}"
        if scatter_dataset:
            oversampled_file = os.path.join(
                "oversample_embeddings", "index.csv"
            )
        else:
            oversampled_file = f"{oversampled_name}_data.pkl"
        oversampled_file = os.path.join(output_dir, oversampled_name)
        # avoid unnecesary loading
        if not overwrite and Path(oversampled_file).exists():
            print("Nothing to do")
        elif embedded is None:
            print(f"Loading cached data from {dataset_file}")
            if scatter_dataset:
                scatter_dir = os.path.join(output_dir, "embeddings")
                embedded = Dataset(data_path=scatter_dir)
            else:
                embedded = load_data(dataset_file)

        num_samples = get_num_samples(embedded, oversample, scatter_dataset)
        oversample_data_dir, oversample_synthetic_dir = oversampling(
            data_args, num_samples, tokenizer, split, output_dir
        )
        oversample_dataset = get_dataset(
            data_args, tokenizer, split, data_dir=oversample_synthetic_dir
        )
        oversample_dataloader = trainer.get_eval_dataloader(oversample_dataset)
        oversample_embedded = embed_from_dataloader(
            oversample_dataloader,
            device,
            model,
            pool,
            scatter_dataset,
            synthetic=True,
            output_dir=oversample_data_dir,
        )
        if scatter_dataset:
            oversample_embedded.extend(embedded)
        else:
            embedded = merge_embedded_data(embedded, oversample_embedded)
            save_data(output_dir, oversampled_name, single_items, **embedded)

        rmtree(oversample_synthetic_dir)


if __name__ == "__main__":
    args = parse_flags()
    main(**vars(args))
