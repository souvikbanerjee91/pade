"""Handles job state persistence."""

import logging
import h5py
import collections

from StringIO import StringIO
from pade.schema import Schema
from pade.model import Model
import numpy as np

TableWithHeader = collections.namedtuple('TableWithHeader', ['header', 'table'])

class Input(object):

    """Raw(ish) input for the job."""
    
    def __init__(self):

        self.table = None
        """The raw data

        (feature x sample) ndarray.

        """

        self.feature_ids = None
        """Array of feature ids"""

    def import_table(self, path):
        """Load the given input file into memory.

        :param path:
          Path to an input file, which must be a tab-delimited file
          with a header line.
        
        """
        logging.info("Loading table from " + path)
        logging.info("Counting rows and columns in input file")

        with open(path) as fh:

            headers = fh.next().rstrip().split("\t")
            num_cols = len(headers) - 1
            num_rows = 0
            for line in fh:
                num_rows += 1

        logging.info(
            "Input has {features} features and {samples} samples".format(
                features=num_rows,
                samples=num_cols))

        logging.info("Creating raw data table")

        table = np.zeros((num_rows, num_cols), float)
        log_interval = int(num_rows / 10)
        table = np.zeros((num_rows, num_cols))
        ids = []

        with open(path) as fh:

            headers = fh.next().rstrip().split("\t")

            for i, line in enumerate(fh):
                row = line.rstrip().split("\t")
                ids.append(row[0])
                table[i] = [float(x) for x in row[1:]]
                if (i % log_interval) == log_interval - 1:
                    logging.debug("Copied {0} rows".format(i + 1))

        self.table = table
        self.feature_ids = ids

    


class Settings:

    """The settings that control how the job is run."""

    def __init__(self):
        self.stat_name = None
        """Name of the statistic to use."""

        self.num_bins = None
        """Number of bins used to discretize statistic space"""

        self.num_samples = None
        """Max number of samples to use for permutation test or bootstrapping"""

        self.sample_from_residuals = None
        """If true, sample from residuals rather than raw values."""

        self.sample_with_replacement = None
        """If true, do sampling with replacement (bootstrapping).

        If false, do permutation test.

        """

        self.block_variables = None
        """List of "blocking" or "nuisance" variables."""

        self.condition_variables = None
        """List of variables you want to test for differential effects."""

        self.tuning_params = None
        """Optional list of tuning parameters for statistic."""

        self.equalize_means = None
        """If true, shift the values so the mean of each group is 0."""

        self.min_conf = None
        """Minimum confidence level to report on."""

        self.conf_interval = None
        """Interval of confidence values to report on."""


class Results:
    
    def __init__(self):
    
        self.bins = None
        self.bin_to_unperm_count = None
        self.bin_to_mean_perm_count = None
        self.bin_to_score = None
        self.feature_to_score = None
        self.raw_stats = None
        self.summary_counts = None
        self.summary_bins = None
        self.best_param_idxs = None
        self.sample_indexes = None
        self.group_means = None
        self.coeff_values = None
        self.fold_change = None
        self.order_by_foldchange_original = None
        self.order_by_score_original = None


def save_input(input, db):
    ids = input.feature_ids
    # Saving feature ids is tricky because they are strings
    dt = h5py.special_dtype(vlen=str)
    input.table       = db.create_dataset("table", data=input.table)
    input.feature_ids = db.create_dataset("feature_ids", (len(ids),), dt)
    for i, fid in enumerate(ids):
        input.feature_ids[i] = fid

def save_schema(schema, db):
    schema_str = StringIO()
    schema.save(schema_str)
    db.attrs['schema'] = str(schema_str.getvalue())


def save_settings(settings, db):
        
    db.create_dataset("tuning_params", data=settings.tuning_params)
    db.attrs['stat_name'] = settings.stat
    db.attrs['num_bins'] = settings.num_bins
    db.attrs['num_samples'] = settings.num_samples
    db.attrs['sample_from_residuals'] = settings.sample_from_residuals
    db.attrs['sample_with_replacement'] = settings.sample_with_replacement
    db.attrs['condition_variables'] = settings.condition_variables
    db.attrs['block_variables'] = settings.block_variables
    db.attrs['min_conf'] = settings.min_conf
    db.attrs['conf_interval'] = settings.conf_interval

def save_results(results, db):
    results.bins = db.create_dataset("bins", data=results.bins)
    results.bin_to_mean_perm_count = db.create_dataset("bin_to_mean_perm_count", data=results.bin_to_mean_perm_count)
    results.bin_to_unperm_count   = db.create_dataset("bin_to_unperm_count", data=results.bin_to_unperm_count)
    results.bin_to_score = db.create_dataset("bin_to_score", data=results.bin_to_score)
    results.feature_to_score = db.create_dataset("feature_to_score", data=results.feature_to_score)
    results.raw_stats = db.create_dataset("raw_stats", data=results.raw_stats)

    summary = db.create_group('summary')
    summary['bins']            = results.summary_bins
    summary['counts']          = results.summary_counts
    summary['best_param_idxs'] = results.best_param_idxs

    results.sample_indexes = db.create_dataset("sample_indexes", data=results.sample_indexes)

    save_table(db, results.group_means, 'group_means')
    save_table(db, results.fold_change, 'fold_change')
    save_table(db, results.coeff_values, 'coeff_values')

    orderings = db.create_group('orderings')
    orderings['by_score_original'] = results.order_by_score_original
    orderings['by_foldchange_original'] = results.order_by_foldchange_original

def save_table(db, table, name):
    db.create_dataset(name, data=table.table)
    db[name].attrs['headers'] = table.header        
    
def load_table(db, name):
    ds = db[name]
    if ds is None:
        raise Exception("No dataset called " + str(name)) 
    return TableWithHeader(ds.attrs['headers'], ds[...])


def load_input(db):
    input = Input()
    input.table = db['table'][...]
    input.feature_ids = db['feature_ids'][...]
    return input

def load_schema(db):
    schema_str = StringIO(db.attrs['schema'])
    return Schema.load(schema_str)

def load_settings(db):
    s = Settings()
    s.stat_name = db.attrs['stat_name']
    s.num_bins = db.attrs['num_bins']
    s.num_samples = db.attrs['num_samples']
    s.sample_from_residuals = db.attrs['sample_from_residuals']
    s.sample_with_replacement = db.attrs['sample_with_replacement']
    s.condition_variables = list(db.attrs['condition_variables'])
    s.block_variables = list(db.attrs['block_variables'])
    s.min_conf = db.attrs['min_conf']
    s.conf_interval = db.attrs['conf_interval']
    s.tuning_params = db['tuning_params'][...]
    return s

def load_results(db):

    results = Results()

    results.bins = db['bins'][...]
    results.bin_to_unperm_count    = db['bin_to_unperm_count'][...]
    results.bin_to_mean_perm_count = db['bin_to_mean_perm_count'][...]
    results.bin_to_score           = db['bin_to_score'][...]
    
    results.feature_to_score = db['feature_to_score'][...]
    results.raw_stats = db['raw_stats'][...]

    # Summary counts by bin, based on optimal tuning params at each level
    results.summary_bins    = db['summary']['bins'][...]
    results.summary_counts  = db['summary']['counts'][...]
    results.best_param_idxs = db['summary']['best_param_idxs'][...]

    results.sample_indexes = db['sample_indexes'][...]

    # Group means, coefficients, and fold change, with the header information
    results.group_means  = load_table(db, 'group_means')
    results.coeff_values = load_table(db, 'coeff_values')
    results.fold_change  = load_table(db, 'fold_change')
    # Orderings
    results.ordering_by_score_original      = db['orderings']['by_score_original'][...]
    results.ordering_by_foldchange_original = db['orderings']['by_foldchange_original'][...]

    return results

class Job:

    """Interface for the HDF5 file that we use to persist the job state."""

    def __init__(self, 
                 schema=None,
                 schema_path=None,
                 path=None):

        self.input = Input()
        self.settings = None
        self.results = Results()
        self.schema_path = schema_path
        self.path = path
        self.file = None
        self.schema = schema


    def save(self):
        logging.info("Saving job results to " + self.path)
        db = h5py.File(self.path, 'w')

        save_input(self.input, db)
        save_schema(self.schema, db)
        save_settings(self.settings, db)
        save_results(self.results, db)

        db.close()


    def load(self):

        logging.info("Loading job results from " + self.path)
        db = None
        try:
            db = h5py.File(self.path, 'r')
        except IOError as e:
            raise IOError("While trying to load database from " + self.path, e)

        self.settings = load_settings(db)
        self.input    = load_input(db)
        self.schema   = load_schema(db)
        self.results  = load_results(db)

        db.close()
        logging.info("Done loading results")


    def layout(self, variables):
        s = self.schema
        return [s.indexes_with_assignments(a)
                for a in s.possible_assignments(variables)]

    @property
    def full_model(self):
        return Model(self.schema, "*".join(self.settings.block_variables + self.settings.condition_variables))

    @property
    def reduced_model(self):
        return Model(self.schema, "*".join(self.settings.block_variables))

    @property
    def condition_layout(self):
        return self.layout(self.settings.condition_variables)

    @property
    def block_layout(self):
        return self.layout(self.settings.block_variables)

    @property
    def full_layout(self):
        return self.layout(self.settings.block_variables + self.settings.condition_variables)
