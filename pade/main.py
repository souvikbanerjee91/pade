#!/usr/bin/env python

# Files:
#  + raw input file
#  + pade_schema.yaml
#  + pade_raw.hdf5
#  + pade_results.hdf5



"""The main program for pade."""

from __future__ import absolute_import, print_function, division

# External imports

import argparse
import csv
import errno
import jinja2
import logging
import numpy as np
import h5py
import os
import os.path
import sys
import scipy.stats
import celery
import pade.tasks
import textwrap
import time
import pade.config
import webbrowser
import urllib2
import pade.analysis as an

from collections import namedtuple
from numpy.lib.recfunctions import append_fields
from pade.model import Job, Model, Settings, Input, Results, Schema
from pade.stat import GroupSymbols, stat_names, glm_families
from pade.metadb import JobMeta
from threading import Thread

REAL_PATH = os.path.realpath(__file__)

class UsageException(Exception):
    """Thrown when the user gave invalid parameters."""
    pass

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

########################################################################
###
### Command-line interface
###

def print_summary(job):
    print("""
Summary of features by confidence level:

Confidence |   Num.   | Tuning
   Level   | Features | Param.
-----------+----------+-------""")
    for i in range(len(job.summary.counts) - 1):
        print("{bin:10.1%} | {count:8d} | {param:0.4f}".format(
                bin=job.summary.bins[i],
                count=int(job.summary.counts[i]),
                param=job.settings.tuning_params[job.summary.best_param_idxs[i]]))


########################################################################
#
# Handlers for command-line actions
#
    
def do_setup(args):
    schema = init_job(
        infile=args.infile,
        schema_path=args.output,
        factors={f : [] for f in args.factor})

    print("""
I have generated a schema for your input file, with factors {factors},
and saved it to "{filename}". You should now edit that file to set the
factors for each sample. The file contains instructions on how to edit
it.

Once you have finished the schema, you will need to run "pade run" to
do the analysis. See "pade run -h" for its usage.
""".format(factors=schema.factors, filename=args.output))

def do_makesamples(args):

    settings = Settings(
        num_samples=args.num_samples,
        block_variables=args.block,
        condition_variables=args.condition,
        stat='f')

    schema = load_schema(args.schema)
    input  = Input.from_raw_file(args.infile, schema, limit=1)
    job = Job(input=input,
              settings=settings,
              schema=schema)

    res = an.new_sample_indexes(job)
    if args.output is None:
        output = sys.stdout
    else:
        output = args.output

    output.write("# Block layout:     " + str(job.block_layout) + "\n")
    output.write("# Condition layout: " + str(job.condition_layout) + "\n")

    test = GroupSymbols(job.condition_layout)

    for row in res:
        for x in row:
            output.write(' {:3d}'.format(x))
        output.write(" # " + test(np.array(row)) + "\n")

def quote_and_join(xs):
    xs = [ '"' + str(x) + '"' for x in xs ]
    if len(xs) == 0:
        return ""
    if len(xs) == 1:
        return xs[0]
    elif len(xs) == 2:
        return xs[0] + " and " + xs[1]
    else:
        xs[-1] = "and " + xs[-1]
        return ", ".join(xs)


def validate_settings(schema, settings):
    vars = set(settings.condition_variables + settings.block_variables)
    known_vars = set(schema.factors)
    bad_vars = vars.difference(known_vars)
    if len(bad_vars) > 0:
        
        raise UsageException(
            "Unknown variables " + quote_and_join(bad_vars) + ".  Valid variables are " + quote_and_join(sorted(known_vars)) + "." )

def do_run(args):
    print("Analyzing {filename}, which is described by the schema {schema}."
          .format(filename=args.infile,
                  schema=args.schema))

    infile = os.path.abspath(args.infile)
    db     = os.path.abspath(args.output)

    schema = load_schema(args.schema)
    settings = args_to_settings(args)

    validate_settings(schema, settings)

    steps = pade.tasks.steps(
        infile_path=infile,
        schema=schema,
        settings=settings,
        sample_indexes_path=args.sample_indexes,
        path=db,
        job_id=0)

    if args.distrib:
        celery.chain(steps)().get()
    else:
        for step in steps:
            start = time.time()
            res = step.apply()
            end = time.time()
            if not res.successful():
                raise Exception(res.traceback)
            logging.info("Task " + str(step) + " completed in " + str(end - start) + " seconds")

    job = pade.tasks.load_job(db)
    print_summary(job)

    print("""
The results for the job are saved in {path}. To generate a text
report, run:

  {pade} report --output REPORT_FILE {path}

To launch a small web server to generate HTML reports, run:

  {pade} view {path}
""".format(path=args.output,
          pade=sys.argv[0]))

def do_server(args):
    import pade.http.server

    if args.prod:
        config = pade.config.search()

    else:
        config = pade.config.default
    app = pade.http.server.PadeRunner(config)
    if args.debug:
        app.debug = True
    app.run(port=args.port)

def do_view(args):

    import pade.http.server
    app = pade.http.server.PadeViewer()
    if args.debug:
        app.debug = True

    job_dbs = []
    for i, path in enumerate(args.pade_results):
        job_dbs.append(
            JobMeta(i, path, path, imported=True))
    pade.http.jobdetails.job_dbs = job_dbs

    def open_browser():
        url = "http://localhost:5000"

        for i in range(10):
            code = 0
            try:
                resp = urllib2.urlopen(url)
                code = resp.getcode()
                webbrowser.open("http://localhost:5000")                    
                return
            except urllib2.URLError as e:
                time.sleep(1)
            
        print("I can't seem to start the server")

    t = Thread(target=open_browser)
        
    t.start()
    app.run(port=args.port)

    
def do_report(args):
    path = args.pade_results

    print("Generating report for result database {job}.".format(job=path))
    job = pade.tasks.load_job(path)
    filename = args.output
    save_text_output(job, filename=filename)
    print("Saved text report to ", filename)



def args_to_settings(args):

    schema = load_schema(args.schema)

    # If they said paired, override the choice of stat
    if args.paired:
        logging.info("You've given the --paired option, so I'll use a one-sample t-test.")
        stat = 't'
    else:
        stat = args.stat

    if stat == 'glm':
        if args.glm_family == '':
            msg = ("If you give --stat glm, you must specify a distribution " +
                   "family with the --glm-family option. Valid arguments " +
                   "for --glm-family are " + 
                   quote_and_join(pade.stat.glm_families()) + ".")
            raise UsageException(msg)

    if args.glm_family != '':
        if stat != 'glm':
             msg = ("If you specify a distribution family with the --glm-family "
                    "option, you must also specify --stat glm.")
             raise UsageException(msg)

    if args.shrink == True:
        if args.glm_family != 'negative_binomial':
            msg = ("Option --shrink can only be used with " + 
                   "--glm-family negative_binomial.")
            raise UsageException(msg)

    # Block and condition variables
    if len(args.block) > 0 or len(args.condition) > 0:
        block_variables = args.block
        condition_variables = args.condition
        
    elif args.full_model is not None:
        full_model    = Model(schema, args.full_model)
        reduced_model = Model(schema, args.reduced_model)
        block_variables     = set(reduced_model.expr.variables)
        condition_variables = set(full_model.expr.variables).difference(block_vars)

    elif len(schema.factors) == 1:
        block_variables = []
        condition_variables = schema.factors

    else:
        raise(UsageException("You have more than one factor, so please specify one to test using --condition (or -c)"))

    # Tuning params
    if args.tuning_param is None or len(args.tuning_param) == 0 :
        tuning_params = np.array(pade.model.DEFAULT_TUNING_PARAMS)
    else:
        tuning_params = np.array(args.tuning_param)

    if args.equalize_means_ids is None:
        equalize_means_ids = None
    else:
        equalize_means_ids = set([line.rstrip() for line in equalize_means_ids])

    return pade.model.Settings(
        num_bins=args.num_bins,
        num_samples=args.num_samples,
        sample_from_residuals=args.sample_from_residuals,
        sample_with_replacement=args.sample_with_replacement,
        summary_min_conf=args.summary_min_conf,
        summary_step_size=args.summary_step_size,
        equalize_means_ids=equalize_means_ids,
        tuning_params=tuning_params,
        block_variables=block_variables,
        condition_variables=condition_variables,
        stat=stat,
        glm_family=args.glm_family,
        equalize_means=args.equalize_means,
        shrink=args.shrink
        )

def load_schema(path):
    try:
        with open(path) as f:
            return Schema.load(f)
    except IOError as e:
        raise UsageException("Couldn't load schema: " + e.filename + ": " + e.strerror)    



def save_text_output(job, filename):

    (num_rows, num_cols) = job.input.table.shape
    num_cols += 2
    table = np.zeros((num_rows, num_cols))

    # Best tuning param for each feature
    idxs = np.argmax(job.results.feature_to_score, axis=0)
    table = []

    # For each row in the data, add feature id, stat, score, group
    # means, and raw values.
    logging.info("Building internal results table")

    for i in range(len(job.input.table)):
        row = []

        # Feature id
        row.append(job.input.feature_ids[i])
        
        # Best stat and all stats
        row.append(job.results.raw_stats[idxs[i], i])
        for j in range(len(job.settings.tuning_params)):
            row.append(job.results.raw_stats[j, i])
        
        # Best score and all scores
        row.append(job.results.feature_to_score[idxs[i], i])
        for j in range(len(job.settings.tuning_params)):
            row.append(job.results.feature_to_score[j, i])
        row.extend(job.results.group_means.table[i])
        row.extend(job.results.coeff_values.table[i])
        row.extend(job.input.table[i])
        table.append(tuple(row))
    schema = job.schema

    cols = []
    Col = namedtuple("Col", ['name', 'dtype', 'format'])
    def add_col(name, dtype, format):
        cols.append(Col(name, dtype, format))

    add_col(schema.feature_id_column_names[0], object, "%s")
    add_col('best_stat', float, "%f")
    for i, alpha in enumerate(job.settings.tuning_params):
        add_col('stat_' + str(alpha), float, "%f")

    add_col('best_score', float, "%f")
    for i, alpha in enumerate(job.settings.tuning_params):
        add_col('score_' + str(alpha), float, "%f")

    for name in job.results.group_means.header:
        add_col("mean: " + name, float, "%f")

    for name in job.results.coeff_values.header:
        add_col("param: " + name, float, "%f")

    for i, name in enumerate(schema.sample_column_names):
        add_col(name, float, "%f")
        
    dtype = [(c.name, c.dtype) for c in cols]

    logging.info("Writing table")
    table = np.array(table, dtype)
    with open(filename, "w") as out:
        out.write("\t".join(c.name for c in cols) + "\n")
        np.savetxt(out, table, 
                   fmt=[c.format for c in cols],
                   delimiter="\t")


def setup_logging(args):
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        filename=args.log,
                        filemode='w')

    console = logging.StreamHandler()
    formatter = logging.Formatter('%(levelname)-8s %(message)s')
    console.setFormatter(formatter)

    if args.debug:
        console.setLevel(logging.DEBUG)
    elif args.verbose:
        console.setLevel(logging.INFO)
    elif args.func == do_server:
        console.setLevel(logging.INFO)
    else:
        console.setLevel(logging.ERROR)

    logging.getLogger('').addHandler(console)



def main():
    """Run pade."""

    args = get_arguments()
    setup_logging(args)
    logging.info('Pade starting')

    start = time.time()
    try:
        args.func(args)

    except UsageException as e:
        print("")
        logging.fatal("Pade exiting because of usage error")
        print("")
        print(fix_newlines(e.message))
        exit(1)
    end = time.time()
    
    logging.info('Pade finished in ' + str(end - start) + ' seconds')

def init_schema(infile=None):
    """Creates a new schema based on the given infile.

    Does not save it or make any changes to the state of the file
    system.

    """
    csvfile = csv.DictReader(infile, delimiter="\t")
    roles = ['sample' for i in csvfile.fieldnames]
    roles[0] = 'feature_id'
    return Schema(column_names=csvfile.fieldnames, column_roles=roles)


def init_job(infile, factors, schema_path=None):

    if isinstance(infile, str):
        infile = open(infile)
    schema = init_schema(infile=infile)    

    for name, values in factors.items():
        schema.add_factor(name, values)

    mode = 'w'
    with open(schema_path, mode) as out:
        logging.info("Saving schema to " + out.name)
        schema.save(out)

    return schema

########################################################################
#
# Parsing command line args
#

    
def get_arguments():
    """Parse the command line options and return an argparse args
    object."""
    
    uberparser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    subparsers = uberparser.add_subparsers(
        title='actions',
        description="""Normal usage is to run 'pade setup -o schema.yaml --factor <FACTOR> ... <INPUT>', then manually edit the schema.yaml file, then run 'pade run -f schema.yaml <INPUT> [OPTIONS]'.
""")

    # Set up "parent" parser, which contains some arguments used by all other parsers
    parents = argparse.ArgumentParser(add_help=False)
    parents.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="Be verbose")
    parents.add_argument(
        '--debug', '-d', 
        action='store_true',
        help="Print debugging information")
    parents.add_argument(
        '--log',
        default="pade.log",
        help="Location of log file")

    model_parent = argparse.ArgumentParser(add_help=False)
    model_parent.add_argument(
        '--block',
        '-b',
        default=[],
        help="""Specify a variable to use for blocking. You can specify this multiple times if there are multiple blocking variables.""",
        action='append')
    
    model_parent.add_argument(
        '--condition',
        '-c',
        default=[],
        help="""Specify a variable that represents an experimental condition. Currently we only support one test condition.""",
        action='append')

    model_parent.add_argument(
        '--full-model', '-M',
        help=argparse.SUPPRESS) #"""Specify the 'full' model as an expression, like 'batch * treated'"""

    model_parent.add_argument(
        '--reduced-model', '-m',
        help=argparse.SUPPRESS) #"""Specify the 'reduced' model as an expression, like 'batch'."""

    # Sampling parent
    sampling_parent = argparse.ArgumentParser(add_help=False)
    sampling_parent.add_argument(
        '--num-samples', '-R',
        type=int,
        default=pade.model.DEFAULT_NUM_SAMPLES,
        help="The number of samples to use if bootstrapping, or the maximum number of permutations to use if doing permutation test.")
    sampling_parent.add_argument(
        '--sample-with-replacement',
        action='store_true',
        default=pade.model.DEFAULT_SAMPLE_WITH_REPLACEMENT,
        help="""Use sampling with replacement (bootstrapping) rather than permutation""")

    # Input file
    infile_parent = argparse.ArgumentParser(add_help=False)
    infile_parent.add_argument(
        'infile',
        help="""Name of input file""",
        default=argparse.SUPPRESS,
        )
    schema_in_parent = argparse.ArgumentParser(add_help=False)
    schema_in_parent.add_argument(
        '--schema', '-f',
        help="The schema YAML file to load",
        required=True)

    db_in_parent = argparse.ArgumentParser(add_help=False)
    db_in_parent.add_argument(
        'pade_results', 
        nargs='+',
        help="Path to the db file to read results from")

    ###
    ### Add sub-parsers
    ###

    setup_parser = subparsers.add_parser(
        'setup',
        help="""Set up the job configuration. This reads the input file and
                outputs a YAML file that you then need to fill out in order to
                properly configure the job.""",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        parents=[parents, infile_parent])

    run_parser = subparsers.add_parser(
        'run',
        help="""Run the job.""",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        parents=[parents, sampling_parent, infile_parent, schema_in_parent, model_parent])

    report_parser = subparsers.add_parser(
        'report',
        help="""Generate report""",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        parents=[parents])

    server_parser = subparsers.add_parser(
        'server',
        help="""Start server to show results""",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        parents=[parents])

    view_parser = subparsers.add_parser(
        'view',
        help="""View results of a job in a browser""",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        parents=[parents, db_in_parent])

    makesamples_parser = subparsers.add_parser(
        'makesamples',
        help="""Generate samples for a schema/input file combination""",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        parents=[parents, infile_parent, sampling_parent, schema_in_parent, model_parent])

    ###
    ### Custom args for setup parser
    ###

    setup_parser.add_argument(
        '--factor',
        action='append',
        required=True,
        help="""A class that can be set for each sample. You can
        specify this option more than once, to use more than one
        class.""")
    setup_parser.add_argument(
        '--output', '-o',
        help="Path to write the schema file to",
        required=True)

    ###
    ### Custom args for run parser
    ###

    run_parser.add_argument(
        '--output', '-o',
        help="Path to the binary output file",
        required=True)

    run_parser.add_argument(
        '--distrib',
        help="Distribute work",
        action='store_true')

    run_parser.add_argument(
        '--sample-indexes',
        help="""File specifying lists of indexes to use for sampling. See 'pade makesamples'.""")

    grp = run_parser.add_argument_group(
        title="confidence estimation arguments",
        description="""These options control how we estimate the confidence levels. You can probably leave them unchanged, in which case I'll compute it using a permutation test with an f-test as the statistic, using a maximum of 1000 permutations.""")
    grp.add_argument(
        '--stat', '-s',
        choices=stat_names(),
        default='f',
        help="The statistic to use.")

    grp.add_argument(
        '--glm-family',
        choices=glm_families(),
        default='N/A',
        help="The distribution family to use for the 'glm' stat.")

    grp.add_argument(
        '--shrink',
        action='store_true',
        default=False,
        help="Calculate dispersion for negative binomial glm using shrinkage method.")

    grp.add_argument(
        '--tuning-param',
        type=float,
        action='append',
        help="""For statistics that take some type of tuning parameter, you may optionally specify that parameter with this option. Specify it more than once and I'll search over all the tuning params and use the one that gives the highest power at each confidence level.""")

    grp.add_argument(
        '--paired', 
        action='store_true',
        default=False,
        help="Indicates that the input is paired. Synonym for '--stat one_sample_t_test'.")

    grp.add_argument(
        '--num-bins',
        type=int,
        default=pade.model.DEFAULT_NUM_BINS,
        help="Number of bins to divide the statistic space into. You probably don't need to change this.")

    grp.add_argument(
        '--sample-from-residuals',
        default=pade.model.DEFAULT_SAMPLE_FROM_RESIDUALS,
        action='store_true',
        help="""Sample from residuals rather than raw data.""")

    grp.add_argument(
        '--summary-min-conf',
        default=pade.model.DEFAULT_SUMMARY_MIN_CONF,
        type=float,
        help="Smallest confidence level to report")

    grp.add_argument(
        '--summary-step-size',
        default=pade.model.DEFAULT_SUMMARY_STEP_SIZE,
        type=float,
        help="Interval of confidence levels")

    grp.add_argument(
        '--equalize-means',
        action='store_true',
        dest='equalize_means',
        default=pade.model.DEFAULT_EQUALIZE_MEANS,
        help="""Shift values of samples within same group for same feature so that their mean is 0 before the permutation test. This will likely cause Pade to be more conservative in selecting features.""")

    grp.add_argument(
        '--equalize-means-ids',
        type=file,
        help="""File giving list of feature ids to equalize means for. The file must contain each id by itself on its own line, with no header row.""")


    ###
    ### Custom args for report parser
    ###

    report_parser.add_argument(
        '--output', '-o',
        required=True,
        help="""Location to write report to""")
    report_parser.add_argument(
        'pade_results', 
        help="Path to the db file to read results from")

    ###
    ### Custom args for server parser
    ###

    server_parser.add_argument(
        '--port',
        type=int,
        help="Specify the port for the server to listen on")
    server_parser.add_argument(
        '--prod',
        action='store_true',
        help="Indicates that this is a 'production' instance")
    view_parser.add_argument(
        '--port',
        type=int,
        help="Specify the port for the server to listen on")

    

    ###
    ### Custom args for server parser
    ###

    makesamples_parser.add_argument(
        '--output', '-o',
        type=argparse.FileType(mode='w'),
        help="File to write sample indexes to")

    defaults = [ (report_parser,      do_report),
                 (run_parser,         do_run),
                 (setup_parser,       do_setup),
                 (server_parser,      do_server),
                 (view_parser,        do_view),
                 (makesamples_parser, do_makesamples) ]
                 
    for (parser, fn) in defaults:
        parser.set_defaults(func=fn)
    
    return uberparser.parse_args()



if __name__ == '__main__':
    main()
