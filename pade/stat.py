"""Low-level statistical methods.

This module should be general-purpose, and not have any dependencies
on the data model used in PADE or the workflow. The idea is that we
may use these functions outside of the standard PADE workflow.

"""

import numbers
import numpy as np
import numpy.ma as ma
import scipy.stats

import collections
from pade.performance import profiling, profiled
from pade.common import *
from pade.layout import *

class UnsupportedLayoutException(Exception):
    """Thrown when a statistic is used with a layout that it can't support."""
    pass


def group_means(data, layout):
    """Get the means for each group defined by layout.

    Groups data according to the given layout and returns a new
    ndarray with the same number of dimensions as data, but with the
    last dimension replaced by the means according to the specified
    grouping.
    
    One dimensional input:

    >>> group_means(np.array([-1, -3, 4, 6]), [[0, 1], [2, 3]])
    array([-2.,  5.])

    Two dimensional input:

    >>> data = np.array([[-1, -3, 4, 6], [10, 12, 30, 40]])
    >>> layout = [[0, 1], [2, 3]]
    >>> group_means(data, layout) # doctest: +NORMALIZE_WHITESPACE
    array([[ -2.,  5.],
           [ 11., 35.]])

    :param data: An ndarray. Any number of dimensions is allowed.

    :param layout: A :term:`layout` describing the data.

    :return: An ndarray giving the means for each group obtained by
      applying the given layout to the given data.

    """
    # We'll take the mean of the last axis of each group, so change
    # the shape of the array to collapse the last axis down to one
    # item per group.
    shape = np.shape(data)[:-1] + (len(layout),)
    res = np.zeros(shape)

    for i, group in enumerate(apply_layout(data, layout)):
        res[..., i] = np.mean(group, axis=-1)

    return res

def residuals(data, layout):
    """Return the residuals for the given data and layout.

    >>> residuals(np.array([1, 2, 3, 6], float), [[0, 1], [2, 3]])
    array([-0.5,  0.5, -1.5,  1.5])

    :param data: An ndarray. Any number of dimensions is allowed.

    :param layout: A :term:`layout` describing the data.

    :return: The residuals obtained by subtracting the means of the
    groups defined by the layout from the values in data.

    """
    means = group_means(data, layout)
    diffs = []
    groups = apply_layout(data, layout)
    
    for i, group in enumerate(groups):
        these_means = means[..., i].reshape(np.shape(group)[:-1] + (1,))
        diffs.append(group - these_means)
    return np.concatenate(diffs, axis=-1)

def rss(data, layout=None):
    """Return the residual sum of squares for the data and optional layout.

    :param data:
      An n-dimensional array.

    :param layout:
      If provided, the means will becalculated based on the grouping
      given by the layout applied to the last axis of data. Otherwise,
      no grouping will be used.

    >>> rss(np.array([1, 2, 3, 6], float), [[0, 1], [2, 3]])
    5.0

    """

    if layout is None:
        y   = np.mean(data, axis=-1).reshape(np.shape(data)[:-1] + (1,))
        return double_sum((data  - y)  ** 2)

    else:
        r = residuals(data, layout)
        rs = r ** 2
        return np.sum(rs, axis=-1)


class Ftest:
    """Computes the F-test.

    Some sample data

    >>> a = np.array([1., 2.,  3., 6.])
    >>> b = np.array([2., 1.,  1., 1.])
    >>> c = np.array([3., 1., 10., 4.])

    The full layout has the first two columns in one group and the
    second two in another. The reduced layout has all columns in one
    group.

    >>> condition_layout = [[0, 1], [2, 3]]
    >>> block_layout     = [[0, 1, 2, 3]]
    
    Construct one ftest based on our layouts

    >>> ftest = Ftest(condition_layout, block_layout)
    
    Test one row

    >>> round(ftest(a), 1)
    3.6

    Test multiple rows at once

    >>> data = np.array([a, b, c])
    >>> ftest(data)
    array([ 3.6,  1. ,  2.5])

    """

    name = "F-test"

    def __init__(self, condition_layout, block_layout, alphas=None):

        full_layout = intersect_layouts(block_layout, condition_layout)
        if min(map(len, full_layout)) < 2:
            raise UnsupportedLayoutException(
                """I can't use an FTest with the specified layouts, because the intersection between those layouts results in some groups that contain fewer than two samples.""")

        self.layout_full = full_layout
        self.block_layout = block_layout
        self.alphas = alphas

    def __call__(self, data):

        # Degrees of freedom
        p_red  = len(self.block_layout)
        p_full = len(self.layout_full)
        n      = sum(map(len, self.block_layout))

        # Means and residual sum of squares for the reduced and full
        # model
        rss_full = rss(data, self.layout_full)
        rss_red  = rss(data, self.block_layout)

        numer = (rss_red - rss_full) / (p_full - p_red)
        denom = rss_full / (n - p_full)

        if self.alphas is not None:
            denom = np.array([denom + x for x in self.alphas])
        return numer / denom


class OneSampleTTest:
    def __init__(self, alphas=None):
        self.alphas = alphas

    def __call__(self, data):
        n = np.size(data, axis=-1)
        x = np.mean(data, axis=-1)
        s = np.std(data, axis=-1)

        numer = x
        denom = s / np.sqrt(n)
        if self.alphas is not None:
            denom = np.array([denom + x for x in self.alphas])
        return np.abs(numer / denom)


class MeansRatio:

    """Means ratio statistic.

    Supports layouts where there are two experimental conditions, with
    or without blocking.

    :param condition_layout:
      A layout that groups the sample indexes together into groups
      that have the same experimental condition. MeansRatio only
      supports designs where there are exactly two conditions, so
      len(condition_layout) must be 2.

    :param block_layout: 
      If the input has blocking variables, then block layout
      should be a layout that groups the sample indexes together
      by block.

    :param alphas: 
      Optional array of "tuning parameters". 

    :param symmetric:
      If true, gives the inverse of the ratio when the ratio is less
      than 1. Use this when it does not matter which condition is
      greater than the other one.
      
    """

    name = "means ratio"

    def __init__(self, condition_layout, block_layout, alphas=None, symmetric=True):
        conditions = len(condition_layout)
        blocks     = len(block_layout)

        if conditions != 2:
            raise UnsupportedLayoutException(
                """MeansRatio only supports configurations where there are two conditions and n blocks. You have {conditions} conditions and {blocks} blocks.""".format(
                    conditions=conditions,
                    blocks=blocks))

        self.condition_layout  = as_layout(condition_layout)
        self.block_layout      = as_layout(block_layout)
        self.alphas            = alphas
        self.symmetric         = symmetric


    def __call__(self, data):

        conds  = self.condition_layout
        blocks = self.block_layout

        # Build two new layouts. c0 is a list of lists of indexes into
        # the data that represent condition 0 for each block. c1 is
        # the same for data that represent condition 1 for each block.
        c0_blocks = intersect_layouts(blocks, [ conds[0] ])
        c1_blocks = intersect_layouts(blocks, [ conds[1] ])

        # Get the mean for each block for both conditions.
        means = np.array([group_means(data, c0_blocks),
                          group_means(data, c1_blocks)])

        # If we have tuning params, add another dimension to the front
        # of each ndarray to vary the tuning param.  First add the
        # alpha dimension to the front of means, then swap it so the
        # dimensionality becomes (alpha, condition, ...)
        if self.alphas is not None:
            means = np.array([ means + x for x in self.alphas ])
            means = means.swapaxes(0, 1)

        ratio = means[0] / means[1]

        # If we have more than one block, we combine their ratios
        # using the geometric mean.
        ratio = scipy.stats.gmean(ratio, axis=-1)

        # 'Symmetric' means that the order of the conditions does not
        # matter, so we should always return a ratio >= 1. So for any
        # ratios that are < 1, use the inverse.
        if self.symmetric:
            # Add another dimension to the front where and 1 is its
            # inverse, then select the max across that dimension
            ratio_and_inverse = np.array([ratio, 1.0 / ratio])
            ratio = np.max(ratio_and_inverse, axis=0)

        return ratio
        

class OneSampleDifferenceTTest:
    """A one-sample t-test where the input is given as pairs.

    Input with two features (one on each row), eight samples
    arranged as four pairs.

    >>> table = np.array([[3, 2, 6, 4, 9, 6, 7, 3], [2, 4, 4, 7, 5, 1, 8, 3]])

    Pairs are grouped together. Assume we have two conditions, the
    even numbered samples are one condition and the odd numbered ones
    are the other

    >>> block_layout     = [ [0, 1], [2, 3], [4, 5], [6, 7] ]
    >>> condition_layout = [ [0, 2, 4, 6], [1, 3, 5, 7] ]

    Construct the test function with the condition and block layouts.

    >>> test = OneSampleDifferenceTTest(condition_layout, block_layout)

    Apply it to 1d input (the first feature in the table):

    >>> print round(test(table[0]), 7)
    4.472136

    Now 2d input (both features in the table):

    >>> results = test(table)
    >>> print round(results[0], 7)
    4.472136
    >>> print round(results[1], 7)
    0.5656854

    """
    name = "OneSampleDifferenceTTest"

    def __init__(self, condition_layout, block_layout, alphas=None):

        if not layout_is_paired(block_layout):
            raise UnsupportedLayoutException(
                "The block layout " + str(block_layout) + " " +
                "is invalid for a one-sample difference t-test. " +
                "Each block must be a pair, with exactly two items in it")
        
        if len(condition_layout) != 2:
            raise UnsupportedLayoutException(
                "The condition layout " + str(condition_layout) + " " +
                "is invalid for a one-sample difference t-test. " +
                "There must be two conditions, and you have " + 
                str(len(condition_layout)) + ".")

        self.block_layout = block_layout
        self.condition_layout = condition_layout
        self.child = OneSampleTTest(alphas)

    def __call__(self, data):
        
        pairs = map(set, self.block_layout)
        conds = map(set, self.condition_layout)

        idxs_a = []
        idxs_b = []

        for s in pairs:
            idxs_a.extend(s.intersection(conds[0]))
            idxs_b.extend(s.intersection(conds[1]))

        a = data[..., idxs_a]
        b = data[..., idxs_b]

        diffs = data[..., idxs_a] - data[..., idxs_b]

        res = self.child(diffs)
        return res
        
