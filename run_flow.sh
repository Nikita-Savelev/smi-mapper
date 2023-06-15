#!/bin/sh
export LD_LIBRARY_PATH="/usr/local/lib"
export PYTHONPATH=$HOME/usr/project/:$PYTHONPATH
python src/run.py