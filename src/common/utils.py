import itertools
import json
import logging
import os
import random
import shutil
import sys
import time
from copy import deepcopy
from dataclasses import fields
from datetime import datetime

import numpy as np
import pytz
import torch
from torch.utils.tensorboard.summary import hparams

from src.common.dataclass import StepState


def get_result_folder(desc, result_dir, date_prefix=True):
    process_start_time = datetime.now(pytz.timezone("Asia/Seoul"))

    if date_prefix is True:
        _date_prefix = process_start_time.strftime("%Y%m%d_%H%M%S")
        result_folder = f'{result_dir}/{_date_prefix}-{desc}'

    else:
        result_folder = f'{result_dir}/{desc}'

    return result_folder


def set_result_folder(folder):
    global result_folder
    result_folder = folder


def create_logger(log_file=None):
    # print(log_file)
    if 'filepath' not in log_file:
        log_file['filepath'] = log_file['result_dir']

    if 'desc' in log_file:
        log_file['filepath'] = log_file['filepath'].format(desc='_' + log_file['desc'])
    else:
        log_file['filepath'] = log_file['filepath'].format(desc='')

    if 'filename' in log_file:
        filename = log_file['filepath'] + '/' + log_file['filename']
    else:
        filename = log_file['filepath'] + '/' + 'log.txt'

    if not os.path.exists(log_file['filepath']):
        os.makedirs(log_file['filepath'])

    file_mode = 'a' if os.path.isfile(filename) else 'w'

    root_logger = logging.getLogger()
    root_logger.setLevel(level=logging.INFO)
    formatter = logging.Formatter("[%(asctime)s] %(filename)s(%(lineno)d) : %(message)s", "%Y-%m-%d %H:%M:%S")

    for hdlr in root_logger.handlers[:]:
        root_logger.removeHandler(hdlr)

    # write to file
    fileout = logging.FileHandler(filename, mode=file_mode)
    fileout.setLevel(logging.INFO)
    fileout.setFormatter(formatter)
    root_logger.addHandler(fileout)

    # write to console
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root_logger.addHandler(console)


def deepcopy_state(state):
    to = StepState()

    for field in fields(StepState):
        setattr(to, field.name, deepcopy(getattr(state, field.name)))

    return to


def explained_variance(y_pred: np.ndarray, y_true: np.ndarray) -> np.ndarray:
    """
    Computes fraction of variance that ypred explains about y.
    Returns 1 - Var[y-ypred] / Var[y]

    interpretation:
        ev=0  =>  might as well have predicted zero
        ev=1  =>  perfect prediction
        ev<0  =>  worse than just predicting zero

    :param y_pred: the prediction
    :param y_true: the expected value
    :return: explained variance of ypred and y
    """
    if isinstance(y_pred, list):
        y_pred = np.array(y_pred)

    if isinstance(y_true, list):
        y_true = np.array(y_true)

    assert y_true.ndim == 1 and y_pred.ndim == 1
    var_y = np.var(y_true)
    return np.nan if var_y == 0 else 1 - np.var(y_true - y_pred) / var_y


def cal_distance(xy, visiting_seq):
    """
    :param xy: coordinates of nodes
    :param visiting_seq: sequence of visiting node idx
    :return:

    1. Gather coordinates on a given sequence of nodes
    2. roll by -1
    3. calculate the distance
    4. return distance

    """
    desired_shape = tuple(list(visiting_seq.shape) + [2])
    gather_idx = np.broadcast_to(visiting_seq[:, :, None], desired_shape)

    original_seq = np.take_along_axis(xy, gather_idx, 1)
    rolled_seq = np.roll(original_seq, -1, 1)

    segments = np.sqrt(((original_seq - rolled_seq) ** 2).sum(-1))
    distance = segments.sum(1).astype(np.float16)
    return distance


class TimeEstimator:
    def __init__(self):
        self.logger = logging.getLogger('TimeEstimator')
        self.start_time = time.time()
        self.count_zero = 0

    def reset(self, count=1):
        self.start_time = time.time()
        self.count_zero = count - 1

    def get_est(self, count, total):
        curr_time = time.time()
        elapsed_time = curr_time - self.start_time
        remain = total - count
        remain_time = elapsed_time * remain / (count - self.count_zero)

        elapsed_time /= 3600.0
        remain_time /= 3600.0

        return elapsed_time, remain_time

    def get_est_string(self, count, total):
        elapsed_time, remain_time = self.get_est(count, total)

        elapsed_time_str = "{:.2f}h".format(elapsed_time) if elapsed_time > 1.0 else "{:.2f}m".format(elapsed_time * 60)
        remain_time_str = "{:.2f}h".format(remain_time) if remain_time > 1.0 else "{:.2f}m".format(remain_time * 60)

        return elapsed_time_str, remain_time_str

    def print_est_time(self, count, total):
        elapsed_time_str, remain_time_str = self.get_est_string(count, total)

        self.logger.info("Epoch {:3d}/{:3d}: Time Est.: Elapsed[{}], Remain[{}]".format(
            count, total, elapsed_time_str, remain_time_str))


def copy_all_src(dst_root):
    # execution dir
    if os.path.basename(sys.argv[0]).startswith('ipykernel_launcher'):
        execution_path = os.getcwd()
    else:
        execution_path = os.path.dirname(sys.argv[0])

    # home dir setting
    tmp_dir1 = os.path.abspath(os.path.join(execution_path, sys.path[0]))
    tmp_dir2 = os.path.abspath(os.path.join(execution_path, sys.path[1]))

    if len(tmp_dir1) > len(tmp_dir2) and os.path.exists(tmp_dir2):
        home_dir = tmp_dir2
    else:
        home_dir = tmp_dir1

    if 'src' not in home_dir:
        home_dir = os.path.join(home_dir, 'src')

    # make target directory
    dst_path = os.path.join(dst_root, 'src')
    #
    # if not os.path.exists(dst_path):
    #     os.makedirs(dst_path)

    shutil.copytree(home_dir, dst_path, dirs_exist_ok=True)


def check_debug():
    import sys

    eq = sys.gettrace() is None

    if eq is False:
        return True
    else:
        return False


def concat_key_val(*args):
    result = deepcopy(args[0])

    for param_group in args[1:]:

        for k, v in param_group.items():
            result[k] = v

    if 'device' in result:
        del result['device']

    return result


def add_hparams(writer, param_dict, metrics_dict, step=None):
    exp, ssi, sei = hparams(param_dict, metrics_dict)

    writer.file_writer.add_summary(exp)
    writer.file_writer.add_summary(ssi)
    writer.file_writer.add_summary(sei)

    if step is not None:
        for k, v in metrics_dict.items():
            writer.add_scalar(k, v, step)


class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return super(NpEncoder, self).default(obj)


def get_param_dict(args, use_mcts=False, copy_src=True):
    # env_params
    num_demand_nodes = args.num_nodes
    num_depots = args.num_depots
    step_reward = args.step_reward
    env_type = args.env_type
    render_mode = args.render_mode
    test_data_type = args.test_data_type

    # mcts params
    num_simulations = args.num_simulations
    temp_threshold = args.temp_threshold
    noise_eta = args.noise_eta
    cpuct = args.cpuct
    action_space = num_demand_nodes + num_depots
    normalize_value = args.normalize_value
    rollout_game = args.rollout_game

    # model_params
    nn = args.nn
    embedding_dim = args.embedding_dim
    encoder_layer_num = args.encoder_layer_num
    qkv_dim = args.qkv_dim
    head_num = args.head_num
    C = args.C

    # trainer params
    mini_batch_size = args.mini_batch_size
    epochs = args.epochs
    num_episode = args.num_episode
    train_epochs = args.train_epochs
    epoch = args.load_epoch
    load_model = True if epoch is not None else False
    cuda_device_num = args.gpu_id
    num_proc = args.num_proc
    lr = args.lr
    ent_coef = args.ent_coef

    # logging params
    result_dir = args.result_dir
    tb_log_dir = args.tb_log_dir
    model_save_interval = args.model_save_interval
    log_interval = args.log_interval

    # etc
    data_path = args.data_path
    seed = args.seed
    name_prefix = args.name_prefix

    if check_debug():
        seed = 2
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.cuda.manual_seed(seed)
        torch.backends.cudnn.deterministic = True  # type: ignore
        torch.backends.cudnn.benchmark = True  # type: ignore
        args.num_episode = 2

    if use_mcts:
        result_folder_name = parse_saved_model_dir(args, result_dir, name_prefix, mcts_param=True)

    else:
        result_folder_name = parse_saved_model_dir(args, result_dir, name_prefix, mcts_param=False)

    # allocating hyper-parameters
    env_params = {
        'num_nodes': num_demand_nodes,
        'num_depots': num_depots,
        'seed': seed,
        'step_reward': step_reward,
        'env_type': env_type,
        'render_mode': render_mode,
        'test_data_type': test_data_type

    }

    mcts_params = {
        'num_simulations': num_simulations,
        'temp_threshold': temp_threshold,  #
        'noise_eta': noise_eta,  # 0.25
        'cpuct': cpuct,
        'action_space': action_space,
        'normalize_value': normalize_value,
        'rollout_game': rollout_game
    }

    model_params = {
        'nn': nn,
        'embedding_dim': embedding_dim,
        'encoder_layer_num': encoder_layer_num,
        'qkv_dim': qkv_dim,
        'head_num': head_num,
        'C': C,
    }

    h_params = {
        'num_nodes': num_demand_nodes,
        'num_depots': num_depots,
        'num_simulations': num_simulations,
        'temp_threshold': temp_threshold,  # 40
        'noise_eta': noise_eta,  # 0.25
        'cpuct': cpuct,
        'action_space': action_space,
        'normalize_value': normalize_value,
        'model_type': nn,
        'embedding_dim': embedding_dim,
        'encoder_layer_num': encoder_layer_num,
        'qkv_dim': qkv_dim,
        'head_num': head_num,
        'C': C

    }

    run_params = {
        'use_cuda': True,
        'cuda_device_num': cuda_device_num,
        'train_epochs': train_epochs,
        'epochs': epochs,
        'num_episode': num_episode,
        'mini_batch_size': mini_batch_size,
        'num_proc': num_proc,
        'data_path': data_path,
        'ent_coef': ent_coef,

        'logging': {
            'model_save_interval': model_save_interval,
            'log_interval': log_interval,
            'result_folder_name': result_folder_name
        },

        'model_load': {
            'enable': load_model,
            'epoch': epoch
        }
    }

    logger_params = {
        'log_file': {
            'result_dir': result_folder_name,
            'filename': 'log.txt',
            'date_prefix': False
        },
        'tb_log_dir': tb_log_dir
    }

    optimizer_params = {
        'lr': lr,
        'eps': 1e-5,
        'betas': (0.9, 0.9)
    }

    create_logger(logger_params['log_file'])

    if copy_src:
        copy_all_src(result_folder_name)

    return env_params, mcts_params, model_params, h_params, run_params, logger_params, optimizer_params


def dict_product(dicts):
    return list(dict(zip(dicts, x)) for x in itertools.product(*dicts.values()))


def parse_saved_model_dir(args, result_dir, name_prefix, load_epoch=None, mcts_param=False,
                          return_checkpoint=False, ignore_debug=False):
    env_param_nm = f"{args.env_type}/N_{args.num_nodes}-B_{args.num_episode}"
    model_param_nm = f"/{args.nn}-{args.embedding_dim}-{args.encoder_layer_num}-{args.qkv_dim}-{args.head_num}-{args.C}"

    if mcts_param:
        mcts_param_nm = f"/ns_{args.num_simulations}-temp_{args.temp_threshold}-cpuct_{args.cpuct}-" \
                        f"norm_{args.normalize_value}-rollout_{args.rollout_game}-ec_{args.ent_coef:.4f}"

    else:
        mcts_param_nm = ""

    result_folder_name = f"./{result_dir}/{name_prefix}/{env_param_nm}{model_param_nm}{mcts_param_nm}"

    if not ignore_debug and check_debug():
        result_folder_name = "./debug" + result_folder_name[1:]

    if return_checkpoint:
        if load_epoch is not None:
            return f"{result_folder_name}/saved_models/checkpoint-{load_epoch}.pt"

        else:
            return None

    else:
        return result_folder_name


import subprocess

def get_gpu_memory_map():
    """Get the current gpu usage.

    Returns
    -------
    usage: dict
        Keys are device ids as integers.
        Values are memory usage as integers in MB.
    """
    result = subprocess.check_output(
        [
            'nvidia-smi', '--query-gpu=memory.used',
            '--format=csv,nounits,noheader'
        ], encoding='utf-8')
    # Convert lines into a dictionary
    gpu_memory = [int(x) for x in result.strip().split('\n')]
    gpu_memory_map = dict(zip(range(len(gpu_memory)), gpu_memory))
    return gpu_memory_map