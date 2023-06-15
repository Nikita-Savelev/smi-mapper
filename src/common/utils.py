import os
import pickle


def mkdir(path: str):
    if not os.path.exists(path):
        os.makedirs(path)


def mkdirs(paths: list):
    for p in paths:
        mkdir(p)


def save_pkl(obj, filename):
    with open(filename, 'wb') as outp:
        pickle.dump(obj, outp, pickle.HIGHEST_PROTOCOL)


def load_pkl(filename):
    with open(filename, 'rb') as inp:
        return pickle.load(inp)

