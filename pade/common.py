"""Some generally useful functions.

We may want to pull these out of PaGE someday and put them in a shared
project.

"""

import os
import logging
import contextlib
import resource
import numpy as np
import textwrap

def double_sum(data):
    """Returns the sum of data over the first two axes."""
    return np.sum(np.sum(data, axis=-1), axis=-1)


@contextlib.contextmanager
def chdir(path):
    """Context manager for changing working directory.

    cds to the given path, yeilds, then changes back.
    
    """
    cwd = os.getcwd()
    try:
        logging.debug("Changing cwd from " + cwd + " to " + path)
        os.chdir(path)
        yield
    finally:
        logging.debug("Changing cwd from " + path + " back to " + cwd)
        os.chdir(cwd)


@contextlib.contextmanager
def figure(path):
    """Context manager for saving a figure.

    Clears the current figure, yeilds, then saves the figure to the
    given path and clears the figure again.

    """
    try:
        logging.debug("Creating figure " + path)
        plt.clf()
        yield
        plt.savefig(path)
    finally:
        plt.clf()


def fix_newlines(msg):
    """Attempt to wrap long lines as paragraphs.

    Treats each line in the given message as a paragraph. Wraps each
    paragraph to avoid long lines. Returns a string that contains all
    the wrapped paragraphs, separated by blank lines.

    """
    output = ""
    for par in msg.split("\n\n"):
        output += textwrap.fill(textwrap.dedent(par)) + "\n"
    return output

def makedirs(path):
    """Attempt to make the directory.

    Attempt to make each director, and raise an exception if it cannot
    be created. Returns normally if the directory was successfully
    created or if it already existed.

    """
    try:
        os.makedirs(path)
    except OSError as e:
        if not os.path.isdir(path):
            raise e

def assignment_name(a):

    if len(a) == 0:
        return "intercept"
    
    parts = ["{0}={1}".format(k, v) for k, v in a.items()]

    return ", ".join(parts)


def adjust_num_diff(V0, R, num_ids):
    V = np.zeros((6,) + np.shape(V0))
    V[0] = V0
    for i in range(1, 6):
        V[i] = V[0] - V[0] / num_ids * (R - V[i - 1])
    return V[5]