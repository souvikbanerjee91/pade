import sys
import cProfile
import pstats

from pade.tasks import load_job
from pade.analysis import get_stat_fn

if __name__ == '__main__':

    path = sys.argv[1]
    job = load_job(path)
    table = job.input.table
    stat_fn = get_stat_fn(job)

    cProfile.run('stat_fn(table)', sort='time', filename='prof')

    p = pstats.Stats('prof')

    p.strip_dirs().sort_stats('time').print_stats(100)
