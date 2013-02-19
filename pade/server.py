# TODO:
#  Pre-generate histograms of stat distributions

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pade.stat import cumulative_hist
import numpy as np
from flask import Flask, render_template, make_response, request
from pade.db import DB
import argparse
import logging 
import StringIO
from pade.common import *
from bisect import bisect

class PadeApp(Flask):

    def __init__(self):
        super(PadeApp, self).__init__(__name__)
        self.db = None

app = PadeApp()

def figure_response(fig):
    png_output = StringIO.StringIO()
    fig.savefig(png_output)
    response = make_response(png_output.getvalue())
    response.headers['Content-Type'] = 'image/png'
    return response

@app.route("/")
def index():
    logging.info("Getting index")
    return render_template("index.html", db=app.db)

@app.route("/measurement_scatter/<feature_num>")
def measurement_scatter(feature_num):
    
    feature_num = int(feature_num)

    db = app.db
    schema = db.schema
    model = db.full_model
    measurements = db.table[feature_num]
    
    fig = plt.figure()
    ax = fig.add_subplot(
        111,
        title='Measurements',
        xlabel='Group',
        ylabel='Measurement')

    assignments = schema.possible_assignments(model.expr.variables)
    names = [assignment_name(a) for a in assignments]
    grps = [schema.indexes_with_assignments(a) for a in assignments]

    for i, a in enumerate(assignments):

        y = measurements[grps[i]]
        x = [i for j in y]
        ax.scatter(x, y)

    plt.xticks(np.arange(len(names)), names)

    ax.legend(loc='upper_right')
    return figure_response(fig)

@app.route("/measurement_bars/<feature_num>")
def measurement_bars(feature_num):
    
    feature_num = int(feature_num)

    db = app.db
    schema = db.schema
    model = db.full_model
    measurements = db.table[feature_num]
    
    fig = plt.figure()
    ax = fig.add_subplot(
        111,
        title='Measurements for ' + db.feature_ids[feature_num],
        ylabel='Measurement')

    assignments = schema.possible_assignments(model.expr.variables)

    x = np.arange(len(assignments))
    width = 0.8

    y = []
    grps = [schema.indexes_with_assignments(a) for a in assignments]
    names = [assignment_name(a) for a in assignments]
    y = [ np.mean(measurements[g]) for g in grps]
    err = [ np.std(measurements[g]) for g in grps]
    ax.bar(x, y, yerr=err, color='y')
    plt.xticks(x+width/2., names)

    return figure_response(fig)


@app.route("/features/<feature_num>")
def feature(feature_num):
    db = app.db
    schema = db.schema
    feature_num = int(feature_num)
    factor_values = {
        s : { f : schema.get_factor(s, f) for f in schema.factors }
        for s in schema.sample_column_names }

    stats=db.raw_stats[..., feature_num]

    params = db.tuning_params

    bins = np.array([ bisect(db.bins[i], stats[i]) - 1 for i in range(len(params)) ])
    unperm_count=np.array([ db.bin_to_unperm_count[i, bins[i]] for i in range(len(params))])
    mean_perm_count=np.array([ db.bin_to_mean_perm_count[i, bins[i]] for i in range(len(params))])

    adjusted=np.array(adjust_num_diff(mean_perm_count, unperm_count, len(db.table)))

    new_scores = (unperm_count - adjusted) / unperm_count

    max_stat = db.bins[..., -2]
    print "Max stat", max_stat
    return render_template(
        "feature.html",
        feature_num=feature_num,
        feature_id=db.feature_ids[feature_num],
        measurements=db.table[feature_num],
        sample_names=db.schema.sample_column_names,
        factors=db.schema.factors,
        factor_values=factor_values,
        layout=db.full_model.layout,
        tuning_params=db.tuning_params,
        stats=stats,
        bins=bins,
        num_bins=len(db.bins[0]),
        unperm_count=unperm_count,
        mean_perm_count=mean_perm_count,
        adjusted_perm_count=adjusted,
        max_stat=max_stat,
        scores=db.feature_to_score[..., feature_num],
        new_scores=new_scores
        )

@app.route("/details/<conf_level>")
def details(conf_level):
    db = app.db

    ### Process params
    conf_level = int(conf_level)
    alpha_idx = db.best_param_idxs[conf_level]

    page_num = 0
    if 'page' in request.args:
        page_num = int(request.args.get('page'))


    scores = db.feature_to_score[alpha_idx]
    stats = db.raw_stats[alpha_idx]
    min_score = db.summary_bins[conf_level]

    rows_per_page = 50

    orig_idxs = np.arange(len(db.feature_ids))
    all_idxs = None
    order_name = request.args.get('order')
    if order_name is None:
        all_idxs      = np.arange(len(db.feature_ids))
    elif order_name == 'score_original':
        all_idxs = db.ordering_by_score_original[alpha_idx]
    elif order_name == 'foldchange_original':
        all_idxs = db.ordering_by_foldchange_original[..., 1]

    filtered_idxs = all_idxs[scores[all_idxs] > min_score]
    start = page_num * rows_per_page
    end = start + rows_per_page
    idxs = filtered_idxs[ start : end ]

    score=db.summary_bins[conf_level]

    num_pages = int(np.ceil(float(len(filtered_idxs)) / float(rows_per_page)))

    return render_template(
        "conf_level.html",
        num_pages=num_pages,
        conf_level=conf_level,
        min_score=score,
        indexes=idxs,
        group_names=db.group_names,
        coeff_names=db.coeff_names,
        stat_name=db.stat_name,
        scores=scores[idxs],
        stats=scores[idxs],
        means=db.group_means[idxs],
        coeffs=db.coeff_values[idxs],
        feature_ids=db.feature_ids[idxs],
        fold_change=db.fold_change[idxs],
        page_num=page_num)

@app.route("/stat_dist.html")
def stat_dist_plots_page():
    semilogx = request.args.get('semilogx') == 'True'
    return render_template("stat_dist.html", 
                           db=app.db,
                           semilogx=semilogx)

@app.route("/feature_count_and_score_by_stat.html")
def feature_count_and_score_by_stat():
    semilogx = request.args.get('semilogx') == 'True'
    return render_template("feature_count_and_score_by_stat.html", 
                           db=app.db,
                           semilogx=semilogx)

@app.route("/confidence_dist.html")
def confidence_dist():
    return render_template("confidence_dist.html", 
                           db=app.db)

@app.route("/stat_dist/<tuning_param>.png")
def stat_dist_plot(tuning_param):
    max_stat = np.max(app.db.raw_stats)
    tuning_param = int(tuning_param)
    fig = plt.figure()
    ax = fig.add_subplot(
        111,
        title=app.db.stat_name + " distribution over features, $\\alpha = " + str(tuning_param) + "$",
        xlabel=app.db.stat_name + " value",
        ylabel="Features",
        xlim=(0, max_stat))

    plt.hist(app.db.raw_stats[tuning_param], log=False, bins=250)
    return figure_response(fig)

@app.route("/bin_to_score.png")
def bin_to_score_plot():
    data = app.db.bin_to_score
    fig = plt.figure()
    ax = fig.add_subplot(
        111,
        title="Confidence by stat value value",
        xlabel="Statistic value",
        ylabel="Confidence")

    for i, param in enumerate(app.db.tuning_params):
        ax.plot(app.db.bins[i, :-1], data[i], label=str(param))

    if request.args.get('semilogx') == 'True':
        ax.semilogx(base=10)
    ax.legend(loc='lower right')

    return figure_response(fig)

@app.route("/bin_to_features.png")
def bin_to_features_plot():

    params = app.db.tuning_params
    if 'tuning_param_idx' in request.args:
        params = [ params[int(request.args.get('tuning_param_idx'))] ]

    fig = plt.figure()
    ax = fig.add_subplot(
        111,
        title='Features count by statistic value',
        xlabel='Statistic value',
        ylabel='Features')
    db = app.db
    for i, param in enumerate(params):
        ax.plot(db.bins[i, :-1], db.bin_to_mean_perm_count[i], '--', label=str(param) + " permuted")
        ax.plot(db.bins[i, :-1], db.bin_to_unperm_count[i], label=str(param) + " unpermuted")
    if request.args.get('semilogx') == 'True':
        ax.semilogx(base=10)
    ax.legend(loc='upper right')
    return figure_response(fig)

@app.route("/conf_dist.png")
def conf_dist_plot():
    fig = plt.figure()
    ax = fig.add_subplot(
        111,
        title="Feature count by confidence score",
        xlabel="Confidence score",
        ylabel="Features")
    ax.plot(app.db.summary_bins, app.db.summary_counts)
    return figure_response(fig)
    

@app.route("/score_dist_for_tuning_params.png")
def score_dist_by_tuning_param():
    fig = plt.figure()
    ax = fig.add_subplot(
        111,
        title='Features by confidence score',
        xlabel='Confidence',
        ylabel='Features')

    lines = []
    labels = []

    params = app.db.tuning_params
    if 'tuning_param_idx' in request.args:
        params = [ int(request.args.get('tuning_param_idx')) ]

    for i, alpha in enumerate(params):
        bins = np.arange(0.5, 1.0, 0.01)
        hist = cumulative_hist(app.db.feature_to_score[i], bins)
        lines.append(ax.plot(bins[:-1], hist, label=str(alpha)))
        labels.append(str(alpha))
    ax.legend(loc='upper right')

    return figure_response(fig)
