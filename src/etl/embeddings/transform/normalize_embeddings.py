import os
import sys
import argparse

from sklearn.decomposition import PCA

base_path = os.path.dirname(os.path.dirname(__file__))
sys.path.append(base_path)
sys.path.append(os.path.join(base_path, "classify"))

from dataset import (  # noqa: E402
    get_dataset,
    get_x_y_from_dict,
    normalize_dataset,
    save_data,
)


def parse_flags():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d", "--data_path", type=str, required=True,
        help="Path to embeddings dataset"
    )
    parser.add_argument(
        "-n", "--n_components", type=int, required=False, default=50,
        help="Number of components to reduce dimensionality"
    )
    parser.add_argument(
        "--normalize", action="store_true",
        help="Wheter to normalize dataset before applying PCA"
    )
    parser.add_argument(
        "-o", "--output_path", required=True, type=str,
        help="Output path to store embeddings and data file"
    )
    return parser.parse_args()


def main(data_path, n_components, normalize, output_path):
    output_dir = os.path.dirname(output_path)
    output_name = os.path.splitext(os.path.basename(output_path))[0]
    dataset = get_dataset(data_path)
    feature_set = ["embeddings"]
    untouched_features = {
        key: dataset[key]
        for key in dataset.keys()
        if key not in feature_set
    }

    if normalize:
        dataset = normalize_dataset(dataset, feature_set)

    X, y = get_x_y_from_dict(dataset, features=feature_set)
    pca = PCA(n_components=n_components)
    X_pca = pca.fit_transform(X)
    dataset["embeddings"] = X_pca

    save_data(
        output_dir,
        output_name,
        embeddings=X_pca,
        **untouched_features,
    )


if __name__ == "__main__":
    args = parse_flags()
    main(**vars(args))
