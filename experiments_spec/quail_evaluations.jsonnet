local utils = import 'utils.libsonnet';

local common = {
  task_name: 'ee',
  data_dir: 'data/quail',
  fp16: true,
  fp16_opt_level: 'O2',
  max_seq_length: 384,
  overwrite_cache: true,
  per_gpu_eval_batch_size: 32,
  do_test: true,
  model_type: 'bert',
};

// when not training, model_name_or_path must match the model in output_dir in order
// to load from checkpoint, otherwise will download the model from the internet
local models = {
  bert_race: {
    output_dir: 'data/bert-base-uncased-race',
    model_name_or_path: self.output_dir,
  },
  multibert_race: {
    output_dir: 'data/bert-base-multilingual-cased-race',
    model_name_or_path: self.output_dir,
  },
  bert_quail: {
    output_dir: 'data/bert-base-uncased-quail',
    model_name_or_path: self.output_dir,
  },
  multibert_quail: {
    output_dir: 'data/bert-base-multilingual-cased-quail',
    model_name_or_path: self.output_dir,
  },
};

local testsData = {
  modelNames: std.objectFields(models),
  tests: ['high', 'middle'],
  datasetPrefix: 'dev_race_fmt.json',
};

# local modelsTests = [
#   item + '.json'
#   for item in utils.generateCombinationsTwoSets(testsData.modelNames, testsData.tests, '%s-%s')
# ];
local modelsTests = [
  item + '-quail-eval.json'
  for item in testsData.modelNames
];

local modelName(testName) = utils.getStringSegment(testName, '-', 0);
local testOnlyName(testName) = utils.getStringSegment(utils.trimExt(testName), '-', 1);
// from bert-high.sh to test/high
local composeDataId(testName) = {
  DATA_ID: testsData.datasetPrefix,
};

local files = {
  [testName]: std.manifestJsonEx(
    common + models[modelName(testName)] + composeDataId(testName),
    ' '
  )
  for testName in modelsTests
};

local filelist = {
  'quail-eval.filelist': std.join('\n', modelsTests),
};

// object comprehension can only have one item, either filelist or model test files in the export section....
local allFiles = files + filelist;

{
  [fileName]: |||
    %s
  ||| % allFiles[fileName]
  for fileName in std.objectFields(allFiles)
}