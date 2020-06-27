#!/bin/bash

scriptdir=$(dirname -- "$(realpath -- "$0")")
rootdir=$(dirname $scriptdir)
cd $rootdir >/dev/null

# dockerize by default
dockerize=${1:-1}

if ! hash git unzip wget 2>/dev/null; then
  echo '"git", "unzip" and "wget" are necessary, install them first'
  exit 1
fi

# download some repos we want locally, installed in docker
if [[ "$dockerize" -eq 0 ]]; then
  ./install_packages.sh $dockerize
else
  docker build -t quail-experiments .
fi

[[ ! -d data ]] && mkdir -p data

cd - >/dev/null

exit 0
