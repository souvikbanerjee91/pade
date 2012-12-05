

import matplotlib

import matplotlib.pyplot as plt
import numpy as np
import os
from jinja2 import Environment, PackageLoader

def ensure_increases(a):
    """Given an array, return a copy of it that is monotonically
    increasing."""

    for i in range(len(a) - 1):
        a[i+1] = max(a[i], a[i+1])

def ensure_decreases(a):
    for i in range(len(a) - 1):
        pass

class Report:

    def __init__(self, job, output_dir, results):
        self.job           = job
        self.results       = results
        self.output_dir    = output_dir
        self.stats         = results.stats
        self.conf_levels   = results.conf_levels

        self.unperm_counts = results.up.unperm_counts
        self.raw_conf      = results.up.raw_conf
        self.conf_to_count = results.up.conf_to_count
        self.best_params   = results.up.best_params

        self.plot_histograms = True

    def make_report(self):
        cwd = os.getcwd()
        print "Condition names are " + str(self.job.condition_names)
        try:
            os.chdir(self.output_dir)
            self.make_jinja_report()
        finally:
            os.chdir(cwd)

    def stat_hists(self):

        fmt = 'stat_hist_direction_{direction}_level_{level}_class_{cls}.png'

        results = self.results
        res = np.zeros((2, results.num_levels, results.num_classes), 
                       dtype=object)

        print "Plotting histograms"

        directions = ['up', 'down']

        print "Shape of res is " + str(np.shape(res))
        dir_stats = [
            results.best_up_stats_by_level,
            results.best_down_stats_by_level
            ]

        dir_cutoffs = [
            results.cutoffs_by_level('up'),
            results.cutoffs_by_level('down'),
            ]

        xmax = max(np.max(dir_stats[0]),
                   np.max(dir_stats[1]))
        xmin = min(np.min(dir_stats[0]),
                   np.min(dir_stats[1]))

        for idx in np.ndindex(np.shape(res)):
            print idx
            (d, i, c) = idx
            stats = dir_stats[d]

            cutoffs = dir_cutoffs[d]
            filename = fmt.format(direction=d, level=i, cls=c)
            plt.cla()
            plt.hist(stats[i, c], bins=50)
            plt.axvline(x=cutoffs[i, c])
            plt.xlim([xmin, xmax])
            plt.xlabel('Statistic')
            plt.ylabel('Features')
            plt.title('Number of features by statistic')
            plt.savefig(filename) 
            res[d, i, c] = filename
        return res

    def make_jinja_report(self):
        env = Environment(loader=PackageLoader('page'))

        stats = self.stats
        output_dir = self.output_dir

        stat_hists = []
    
        maxstat = np.max(stats)
        minstat = np.min(stats)

        raw_conf_plots = []

        results = self.results

        if self.plot_histograms:
            print "Plotting histograms"
            for i in range(results.num_tests):
                for c in range(1, results.num_classes):
                    filename = 'stat_hist_test_{test}_class_{cls}.png'.format(
                        test=i, cls=c)
                    plt.cla()
                    plt.hist(stats[i, c], bins=50)
                    plt.xlim([minstat, maxstat])
                    plt.xlabel('Statistic')
                    plt.xlabel('Features')
                    plt.title('Number of features by statistic, test {test}, class {cls}'.format(test=i, cls=self.job.condition_names[c]))
                    plt.savefig(filename) 
                    stat_hists.append(filename)

            classes = []
            for c in range(1, results.num_classes):
                with open('stat_hist_class_{cls}.html'.format(cls=c), 'w') as out:
                    template = env.get_template('stat_hist_class.html')
                    stat_hists = [
                        'stat_hist_test_{test}_class_{cls}.png'.format(
                            test=test, cls=c)
                        for test in range(results.num_tests)]
                    out.write(template.render(
                            job=self.job,
                            stat_hists=stat_hists,
                            condition_num=c,
                            ))

        colors = matplotlib.rcParams['axes.color_cycle']
        plt.clf()
        for c in range(1, results.num_classes):
            plt.plot(self.results.conf_levels,
                     self.results.up.best_counts[c],
                     colors[c] + '-^',
                     label=self.job.condition_names[c] + ' up')
            plt.plot(self.results.conf_levels,
                     self.results.down.best_counts[c],
                     colors[c] + '-v',
                     label=self.job.condition_names[c] + ' down')
        plt.legend()
        plt.title('Differentially expressed features by confidence level')
        plt.xlabel('Confidence')
        plt.ylabel('Differentially expressed features')
        plt.savefig('count_by_conf')

        print "Making index"
        with open('index.html', 'w') as out:
            template = env.get_template('index.html')
        
            out.write(template.render(
                    condition_nums=range(1, results.num_classes),
                    results=self.results,
                    job=self.job,
                    levels=results.conf_levels))

        ##
        ## Make the detail page for each level
        ##
            
        up_cutoffs   = results.up_cutoffs_by_level
        down_cutoffs = results.down_cutoffs_by_level
        feature_to_up_conf = results.feature_to_conf_by_conf('up')
        feature_to_down_conf = results.feature_to_conf_by_conf('down')
        up_stats   = results.best_stats_by_level('up')
        down_stats = results.best_stats_by_level('down')

        any_regulated  = np.zeros((results.num_levels, results.num_features), int)

#        print "Up conf to stat is " + str(results.up.conf_to_stat)

#        print "Up cutoffs are " + str(up_cutoffs)
#        print "Down cutoffs are " + str(down_cutoffs)

        determination = np.zeros((results.num_levels, 
                                  results.num_classes,
                                  results.num_features), dtype=int)

        feature_to_conf = np.zeros((results.num_levels,
                                    results.num_classes,
                                    results.num_features))
        
        feature_to_stat = np.zeros((results.num_levels,
                                    results.num_classes,
                                    results.num_features))

        print "Up cutoffs are " + str(up_cutoffs)
        print "Down cutoffs are " + str(down_cutoffs)

        hists = self.stat_hists()

        for i in range(results.num_levels):
            for j in range(results.num_features):
                for c in range(1, results.num_classes):

                    if up_stats[i, c, j] >= up_cutoffs[i, c]:
                        determination[i, c, j] = 1
                        feature_to_stat[i, c, j] = up_stats[i, c, j]
                        feature_to_conf[i, c, j] = feature_to_up_conf[i, c, j]
                    elif down_stats[i, c, j] <= -down_cutoffs[i, c]:
#                        print "Down stats is " + str(down_stats[i, c, j]) + ", cutoff is " + str(-down_cutoffs[i, c])
                        determination[i, c, j] = 2
                        feature_to_stat[i, c, j] = down_stats[i, c, j]
                        feature_to_conf[i, c, j] = feature_to_down_conf[i, c, j]

                any_regulated[i, j] = np.any(determination[i, :, j] > 0)

            with open('conf_level_detail_' + str(i) + '.html', 'w') as out:
                template = env.get_template('features_by_confidence.html')
                out.write(
                    template.render(
                        level=i,
                        hists=hists,
                        condition_nums=range(1, results.num_classes),
                        job=self.job,
                        results=self.results,
                        feature_nums=range(results.num_features),

                        any_determination=any_regulated,

                        feature_to_stat=feature_to_stat,
                        feature_to_conf=feature_to_conf,

                        up_stats=up_stats,
                        feature_to_up_conf=feature_to_up_conf,

                        down_stats=down_stats,
                        determination=determination,
                        feature_to_down_conf=feature_to_down_conf,

))

