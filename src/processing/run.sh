#!/bin/bash

scriptdir=$(dirname -- "$(realpath -- "$0")")
rootdir=$(dirname $scriptdir)
cd $rootdir >/dev/null

fix_experiment_path() {
  local exp=$1
  if [[ " $(basename $1) " =~ " ${exp} " ]]; then
    # just file name
    echo "experiments/${exp}"
  else
    echo "${exp}"
  fi
}

save_experiment_data() {
  local model_dir=$1; shift
  local results_dir=$1; shift
  local exp_name=$1; shift
  for file in ${result_files[@]}; do
    if [[ -f $model_dir/$file ]]; then
      echo "Saving $model_dir/$file $results_dir/${exp_name}_${file}"
      mv $model_dir/$file $results_dir/${exp_name}_${file}
    fi
  done
}

run_experiment() {
  local file=$1; shift
  local script_file="./src/mc-transformers/run_multiple_choice.py"
  if [[ ! -z ${DONT_DOCKERIZE} ]]; then
    inside_docker=""
  else
    inside_docker="nvidia-docker run --rm ${docker_args[@]}"
  fi
  ${inside_docker} python3 ${script_file} $(python3 $json_as_args $file)
}

get_experiments(){
  local args=($@);
  local aux_flist=()
  experiments=()
  for arg in "${args[@]}"; do
    # if it is a filelist, parse it
    if [[ " ${arg##*.} " =~ " filelist " ]]; then
      IFS=$'\n' read -d '' -r -a aux_flist < $arg
      echo "* Read experiments from $arg:"
      echo "* ${aux_flist[@]}"
      for aux in "${aux_flist[@]}"; do 
        experiments+=($aux)
      done
    else
      experiments+=($arg)
    fi
  done
}

ch_to_project_root(){
  # chdir to project root
  scriptdir=$(dirname -- "$(realpath -- "$0")")
  rootdir=$(echo $scriptdir | sed -e 's/\(quail-experiments\).*/\1/')
  cwd=$(pwd)
  cd $rootdir >/dev/null
}

ch_to_project_root

result_files=(
  "is_test_false_eval_results.txt"
  "is_test_false_eval_nbest_predictions.json"
  "is_test_true_eval_results.txt"
  "is_test_true_eval_nbest_predictions.json"
)

results_dir='./results'
[[ ! -d $results_dir ]] && mkdir $results_dir

docker_img="quail-experiments"
docker_args="--shm-size=1g --ulimit memlock=-1 --ulimit stack=67108864 -v `pwd`:/workspace $docker_img"
json_as_args="./src/processing/json_to_program_args.py"

echo "###### Starting experiments $(date)"
total_start_time=$(date -u +%s)

experiments=()
get_experiments $@
echo "* Total experiments:"
echo "* ${experiments[@]}"

for raw_exp in ${experiments[@]}; do
  exp=$(fix_experiment_path $raw_exp)
  echo "*********** $exp *************";
  run_experiment $exp
  # backup experiment_data $exp
  # ToDo := Review this step
  # model_dir=$(sed -n 's/export OUTPUT_DIR=\(.*\)/\1/p' experiments/$exp);
  # exp_name=${exp%.*}
  # save_experiment_data $model_dir $results_dir $exp_name
  echo "********************************";
done

total_end_time=$(date -u +%s)
total_elapsed=$(python3 -c "print('{:.2f}'.format(($total_end_time - $total_start_time)/60.0 ))")
echo "###### End of experiments $(date) ($total_elapsed) minutes"

