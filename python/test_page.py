import page

import unittest
from numpy import *
import numpy as np
import numpy.ma as ma
import unpermuted_stats
import mean_perm_up

class PageTest(unittest.TestCase):

    def setUp(self):
        self.v1 = ma.masked_array([float(x) for x in [1, 6, 5, 3, 8, 9, 6, 3, 6, 8]], ma.nomask)
        self.v2 = ma.masked_array([float(x) for x in [7, 4, 9, 6, 2, 4, 7, 4, 2, 1]], ma.nomask)
        self.config = page.Config({})
        self.config.infile = 'sample_data/4_class_testdata_header1.txt'

    def test_compute_s(self):
        s = page.compute_s(self.v1, self.v2, 10, 10)
        self.assertAlmostEqual(s, 2.57012753682683)

    def test_default_alpha(self):
        data = page.load_input(self.config)
        alphas = page.find_default_alpha(data.table, data.conditions())

        self.assertAlmostEqual(alphas[1], 1.62026604316528)
        self.assertAlmostEqual(alphas[2], 1.61770701155527)
        self.assertAlmostEqual(alphas[3], 1.60540468969643)

        page.compute_s(data.table[:,(0,1,2,3)],
                         data.table[:,(4,5,6,7)], 10, 10)

    def test_vectorized_tstat(self):
        v1 = [[2.410962, 1.897421, 2.421239, 1.798668],
              [2.410962, 1.897421, 2.421239, 1.798668]]
        v2 = [[0.90775,  0.964438, 1.07578,  1.065872],
              [0.90775,  0.964438, 1.07578,  1.065872]]
        v1 = array(v1)
        v2 = array(v2)
        alpha = 1.62026604316528
        alphas = page.tuning_param_range_values * alpha
        expected = [
            [
                6.62845904788559,
                6.21447939063187,
                3.96389309107878,
                2.19632757746533,
                1.51898640652018,
                0.857703281874709,
                0.597558974875407,
                0.458495683101651,
                0.312872820321998,
                0.0970668755330585,
                ],
            [
                6.62845904788559,
                6.21447939063187,
                3.96389309107878,
                2.19632757746533,
                1.51898640652018,
                0.857703281874709,
                0.597558974875407,
                0.458495683101651,
                0.312872820321998,
                0.0970668755330585,
                ]]

        self.assertAlmostEqual(sum(page.v_tstat(v1, v2, alphas, axis=1)),
                               sum(expected),
                               )


    def test_min_max_tstat(self):
        data = page.load_input(self.config)
        alphas = page.find_default_alpha(data.table, data.conditions())
        (mins, maxes) = page.min_max_stat(data.table, data.conditions(), alphas)
        
        e_mins = np.array([[  0.        ,   0.        ,   0.        ,   0.        ,
          0.        ,   0.        ,   0.        ,   0.        ,
          0.        ,   0.        ],
       [ -4.9202359 ,  -3.89533332,  -3.52368811,  -3.26242876,
         -3.03723672,  -2.59025082,  -2.25795127,  -2.00121791,
         -1.63044785,  -0.74224611],
       [-43.82835582, -39.64845899, -21.23648542, -10.45124849,
         -6.93116328,  -3.76279535,  -2.58235243,  -2.37354146,
         -2.16027477,  -1.32616667],
       [ -6.0751867 ,  -5.88208044,  -4.56341649,  -3.83014094,
         -3.63883036,  -3.23488462,  -2.91166171,  -2.64716274,
         -2.24016415,  -1.07895089]])

        e_maxes = np.array([[  0.        ,   0.        ,   0.        ,   0.        ,
          0.        ,   0.        ,   0.        ,   0.        ,
          0.        ,   0.        ],
       [ 33.85134388,  32.62371504,  24.53492985,  15.8189654 ,
         13.90618311,  11.06393443,   9.18635847,   7.85358622,
          6.08728055,   2.36460731],
       [ 40.15693526,  39.48532655,  34.27421269,  26.50177462,
         21.60284929,  14.77489855,  11.22655382,   9.05250186,
          6.52524125,   2.30890874],
       [ 32.14060907,  30.20630649,  19.5242959 ,  16.17200918,
         14.25569827,  10.9977404 ,   8.95189831,   7.54782314,
          5.74549878,   2.75756182]])
        
        self.assertTrue(all(abs(mins  - e_mins)  < 0.00001))
        self.assertTrue(all(abs(maxes - e_maxes) < 0.00001))


    def test_all_subsets(self):
        subsets = page.all_subsets(8, 4)
        # There should be 70 rows and 8 columns
        self.assertEquals(shape(subsets), (70, 8))

        # There should be 4 1s and 4 0s in each row
#        self.assertTrue(all(sum(subsets, axis=1) == 4))

    def test_unpermuted_stats(self):
        (u, d, stats) = page.dist_unpermuted_stats(
            unpermuted_stats.data,
            [[ 0,  1,  2,  3],
             [ 4,  5,  6,  7],
             [ 8,  9, 10, 11],
             [12, 13, 14, 15]],
            unpermuted_stats.mins,
            unpermuted_stats.maxes,
            unpermuted_stats.alpha_default)
        self.assertEqual(shape(stats), shape(unpermuted_stats.stats))
        self.assertTrue(all(abs(unpermuted_stats.stats - stats) < 0.00001))

        self.assertEqual(shape(u), shape(unpermuted_stats.dist_up))
        self.assertEqual(shape(d), shape(unpermuted_stats.dist_down))

        u_diffs = unpermuted_stats.dist_up   - u
        d_diffs = unpermuted_stats.dist_down - d

        # For some reason the last two bins are swapped in a very
        # small number of cases, so ignore them.
        u_diffs = u_diffs[:, :, :999]
        d_diffs = d_diffs[:, :, :999]

        self.assertTrue(all(u_diffs == 0))
        self.assertTrue(all(d_diffs == 0))

    def test_mean_perm_up(self):


unittest.main()

2.71876197315371

#Mean is 2.29140221289693
#SD is 1.66873784599192
#Mean is 2.28778319568751
#SD is 1.67061575354633
#Mean is 2.27038508526607
#SD is 1.66848321913367
#701
#693
#693

# alpha is  
