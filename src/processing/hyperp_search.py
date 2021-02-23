import os
import pandas as pd


from pathlib import Path
from functools import partial
from timeit import default_timer as timer
from hyperopt import (
    hp,
    tpe,
    Trials,
    fmin,
    STATUS_OK,
    STATUS_FAIL,
)

from classification import parse_flags, get_params
from classification import main as classification_main
from hyperp_utils import (
    load_params,
    write_params,
    update_params,
    combination_to_params,
    validate_combination,
)

params_file = Path(os.getcwd()).absolute().joinpath("params.yaml")


def train_eval(args, x):
    params = combination_to_params(x)
    params = update_params(params, load_params(params_file))
    write_params(params, params_file)
    return classification_main(args)


def objective(args, x):
    if not validate_combination(x):
        return {"loss": -100.0, "status": STATUS_FAIL, "time": 0.0}

    start = timer()
    # ToDo := Parse score output
    args.train = True
    args.eval = True
    score = train_eval(args, x)
    end = timer()
    elapsed = end - start
    result = {
        "loss": 1 - score[metric],
        "time": elapsed,
        "status": STATUS_OK,
        "x": x
    }
    result.update({k: v for k, v in score.items()})
    return result


def save_results(trials, results_path):
    results = trials.results
    results_dict = {
        key: [r[key] for r in results]
        for key in results[0] if key not in ["time", "loss"]
    }
    results_dict.update({
        "time": [x["time"] for x in results],
        "loss": [x["loss"] for x in results],
        "x": [x["x"] for x in results],
        "iteration": list(range(len(results)))
    })
    results_df = pd.DataFrame(results_dict)
    results_df = results_df.sort_values("loss", ascending=True)
    results_df.to_csv(results_path)


def setup_data_dir(data_path):
    path = Path(data_path)
    path.mkdir(exists_ok=True, parents=True)
    return path


def main(args):
    evals = get_params()["hyper-search"]["iterations"]
    data_path = setup_data_dir(args.metrics_dir)
    results_path = data_path.joinpath("hyperparam_search.csv")

    space = hp.choice("classifier", [{
        "pipeline": hp.choice("class_pipeline", ["logreg", "mlp"]),
        "normalization": hp.choice("feat_normalization", [True, False]),
        "oversample": hp.choice("feat_oversample", [True, False]),
        "text_length": hp.choice("feat_text_length", [True, False]),
        "embeddings": hp.choice("feat_embeddings", [True, False]),
        "logits": hp.choice("feat_logits", [True, False]),
        "context": hp.choice("feat_context", [True, False]),
        "question": hp.choice("feat_question", [True, False]),
        "endings": hp.choice("feat_endings", [True, False]),
    }])

    trials = Trials()
    _ = fmin(
        fn=partial(objective, args), space=space,
        algo=tpe.suggest, trials=trials,
        max_evals=evals, rstate=args.seed
    )

    save_results(trials, str(results_path))


if __name__ == '__main__':
    main(parse_flags())