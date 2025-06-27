# AlphaRouter

refer to https://www.mdpi.com/1099-4300/27/3/251([https://www.mdpi.com/1099-4300/27/3/251]) 

For training, modify the parameters in the main_pretrain.py, which are depicted as a dictionary consisting keys as the parameter name and the values as the list of possible values.

Note that you must wrap a parameter in a list, even if it contains only one parameter.

For more details on what parameters can be added as keys, please refer to run.py file's argparse section.

For testing without MCTS, repeat the same process for training but run main_test_am.py in the main directory of the repo.

For testing with MCTS,  repeat the same process for training but run main_test_mcts.py in the main directory of the repo.

Note that you must train the neural network first before testing with any of the methods. The default behavior is to use the latest epoch from the saved checkpoints. You may modify it by changing the pivot in the file and so on.

# Requirements

lightning
pytorch
pygame
gymnasium
matplotlib
numpy
pandas

