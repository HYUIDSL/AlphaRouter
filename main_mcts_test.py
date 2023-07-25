import json
import math
from copy import deepcopy
from pathlib import Path

from src.common.utils import dict_product, save_json, cal_average_std, collect_all_checkpoints, get_result_dir
from src.run import parse_args
import torch.multiprocessing as mp
from src.run import run_mcts_test


def run_test(**kwargs):
    import warnings
    warnings.simplefilter("ignore", UserWarning)

    args = parse_args()

    for k, v in kwargs.items():
        setattr(args, k, v)

    # args.num_simulations = args.num_nodes * 2

    score, runtime = run_mcts_test(args)

    print(f"Done! Loaded from :{kwargs['result_dir']}/{kwargs['load_epoch']}. "
          f"Tested on: {kwargs['test_data_idx']}. Scored: {score:.5f} in {runtime:.2f} seconds.")

    return score, runtime, args.test_data_idx, kwargs['load_epoch'], kwargs['result_dir']


def run_parallel_test(param_ranges, num_proc=5):
    """
    Parallel test with multiprocessing
    :param param_ranges: dict of parameter ranges. e.g. {"num_nodes": [1, 2, 3]}

    """
    result_dict = {}
    async_result = mp.Queue()

    def __callback(val):
        async_result.put(val)

    if num_proc > 1:
        pool = mp.Pool(num_proc)

        for params in dict_product(param_ranges):
            all_files, ckpt_root = collect_all_checkpoints(params)
            all_checkpoints = [x.split('/')[-1].split('\\')[-1].split('.ckpt')[0] for x in all_files]
            result_dir = get_result_dir(params, mcts=True)

            for ckpt in all_checkpoints:
                input_params = deepcopy(params)
                input_params['load_epoch'] = ckpt
                input_params['result_dir'] = result_dir

                pool.apply_async(run_test, kwds=input_params, callback=__callback)

        pool.close()
        pool.join()

    else:
        for params in dict_product(param_ranges):
            all_files, ckpt_root = collect_all_checkpoints(params)
            all_checkpoints = [x.split('/')[-1].split('\\')[-1].split('.ckpt')[0] for x in all_files]
            result_dir = get_result_dir(params, mcts=True)

            for ckpt in all_checkpoints:
                input_params = deepcopy(params)
                input_params['load_epoch'] = ckpt
                input_params['result_dir'] = result_dir

                async_result.put(run_test(**input_params))

    if async_result.empty():
        return

    while not async_result.empty():
        score, runtime, test_data_idx, load_epoch, result_dir = async_result.get()

        if result_dir not in result_dict.keys():
            result_dict[result_dir] = {}

        if load_epoch not in result_dict[result_dir].keys():
            result_dict[result_dir][load_epoch] = {}

        if test_data_idx not in result_dict[result_dir][load_epoch].keys():
            result_dict[result_dir][load_epoch][test_data_idx] = {}

        result_dict[result_dir][load_epoch][test_data_idx] = {'score': score, 'runtime': runtime}

    organized_result = {}

    # average of score and runtime for load_epochs should be calculated for each result_dir and average of score and runtime
    # for each load_epoch should be calculated over all test_data_idx

    for result_dir, dir_result in result_dict.items():
        organized_result[result_dir] = {}

        for load_epoch, epoch_result in dir_result.items():
            organized_result[result_dir][load_epoch] = cal_average_std(epoch_result)

    return organized_result


def run_cross_test():
    params = {
        'num_nodes' : 50,   # num_nodes model to load
        'result_dir' : 'pretrained_result',
        'name_prefix' : '',
        'render_mode' : None,
        'num_episode' : 1024,
        'qkv_dim' : 32,
        'env_type' : 'tsp',
        'embedding_dim': 128,
        'test_num': 20,
        'load_epoch': 'best',
        'test_data_type': 'pkl',
    }

    test_result = {}

    for load_from in [20, 50]:
        for test_num in [20, 50]:
            for test_data_idx in range(100):
                params['num_nodes'] = load_from
                params['test_data_idx'] = test_data_idx
                params['test_num'] = test_num

                score, _, test_data_idx = run_test(**params)
                key = f"Trained on {load_from} Test on {test_num}"
                if key not in test_result:
                    test_result[key] = {}

                test_result[key][test_data_idx] = score

    path = f"./result_summary/cross_test_result/mcts/{params['env_type']}"
    if not Path(path).exists():
        Path(path).mkdir(parents=True, exist_ok=False)

    # write the result_dict to a json file
    with open(f"{path}/result.json", 'w') as f:
        json.dump(test_result, f, indent=4)

    # get average score for each key
    avg_result = {}
    for key, result in test_result.items():
        avg_result[key] = sum(result.values()) / len(result)

    print(avg_result)


def main():
    num_env = 64
    num_problems = 100

    run_param_dict = {
        'test_data_type': ['pkl'],
        'env_type': ['tsp'],
        'num_nodes': [20],
        'num_parallel_env': [num_env],
        'test_data_idx': list(range(num_problems)),
        'data_path': ['./data'],
        'activation': ['swiglu'],
        'baseline': ['val', 'mean'],
        'encoder_layer_num': [6],
        'qkv_dim': [32],
        'num_heads': [4],
        'embedding_dim': [128],
        'grad_acc': [1],
        'num_steps_in_epoch': [100 * 1000 // num_env],
        'num_simulations': [20, 50, 100],
        'cpuct': [1.9]
    }

    for num_nodes in [20]:
        run_param_dict['num_nodes'] = [num_nodes]

        result = run_parallel_test(run_param_dict, 4)

        path_format = "./result_summary/mcts_v2"

        for result_dir in result.keys():
            all_result = {}
            path = f"{path_format}/{result_dir}"

            if not Path(path).exists():
                Path(path).mkdir(parents=True, exist_ok=False)

            for load_epoch in result[result_dir].keys():
                # write the result_dict to a json file
                save_json(result[result_dir][load_epoch], f"{path}/{load_epoch}.json")

                all_result[load_epoch] = {'result_avg': result[result_dir][load_epoch]['average'],
                                          'result_std': result[result_dir][load_epoch]['std']}

            save_json(all_result, f"{path}/all_result_avg.json")


def debug():
    num_env = 64
    num_problems = 10

    run_param_dict = {
        'test_data_type': ['pkl'],
        'env_type': ['tsp'],
        'num_nodes': [20],
        'num_parallel_env': [num_env],
        'test_data_idx': list(range(num_problems)),
        'data_path': ['./data'],
        'activation': ['relu', 'swiglu'],
        'baseline': ['val', 'mean'],
        'encoder_layer_num': [6],
        'qkv_dim': [32],
        'num_heads': [4],
        'embedding_dim': [128],
        'grad_acc': [1],
        'num_steps_in_epoch': [100 * 1000 // num_env],
        'cpuct': [1.1]
    }

    for num_nodes in [20]:
        run_param_dict['num_nodes'] = [num_nodes]

        result = run_parallel_test(run_param_dict, 1)
        path_format = "./result_summary/debug/mcts_v2"

        for result_dir in result.keys():
            all_result = {}
            path = f"{path_format}/{result_dir}"

            if not Path(path).exists():
                Path(path).mkdir(parents=True, exist_ok=False)

            for load_epoch in result[result_dir].keys():
                # write the result_dict to a json file
                save_json(result[result_dir][load_epoch], f"{path}/{load_epoch}.json")

                all_result[load_epoch] = {'result_avg': result[result_dir][load_epoch]['average'],
                                          'result_std': result[result_dir][load_epoch]['std']}

            save_json(all_result, f"{path}/all_result_avg.json")

if __name__ == '__main__':
    debug()
    # main()
