import os
import sys
import argparse
import numpy as np

from mc_transformers.utils_mc import processors, Split

base_path = os.path.dirname(os.path.dirname(__file__))
sys.path.append(os.path.join(base_path, "classify"))

from dataset import save_data  # noqa: E402


default_feats = ["contexts", "question", "endings"]


def parse_flags():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d", "--data_dir", required=True, type=str,
        help="Directory containing the dataset"
    )
    parser.add_argument(
        "-t", "--task", required=False, default="generic", type=str,
        help="The task pertaining the dataset (RACE/generic)"
    )
    parser.add_argument(
        "-s", "--split", required=False, default="dev", type=str,
        choices=["train", "dev", "test"],
        help="The split of the dataset to extract embeddings from"
    )
    parser.add_argument(
        "-f", "--features", required=False, type=str, nargs="*", default=None,
        help="Features to extract from the dataset (default: "
        f"{default_feats})"
    )
    parser.add_argument(
        "-o", "--output_path", required=True, type=str,
        help="Output path to store predictions and embeddings"
    )
    return parser.parse_args()


def get_examples(processor, split, data_dir):
    if split == Split.dev:
        examples = processor.get_dev_examples(data_dir)
    elif split == Split.test:
        examples = processor.get_test_examples(data_dir)
    else:
        examples = processor.get_train_examples(data_dir)

    return examples


def get_examples_len(examples, field):
    lens = []
    for sample in examples:
        field_value = sample.__getattribute__(field)
        field_len = len(field_value)
        if isinstance(field_value, list):
            field_len = [len(elem) for elem in field_value]
        lens.append(field_len)

    return np.array(lens)


def main(data_dir, task, split, features, output_path):
    output_dir = os.path.dirname(output_path)
    output_name = os.path.splitext(os.path.basename(output_path))[0]
    processor = processors[task]()
    examples = get_examples(processor, Split(split), data_dir)
    save_dict = dict()
    save_fields = features if features is not None else default_feats

    for field in save_fields:
        field_lens = get_examples_len(examples, field=field)
        save_dict.update(**{field: field_lens})

    save_data(
        output_dir,
        output_name,
        **save_dict
    )


if __name__ == "__main__":
    args = parse_flags()
    main(**vars(args))
