# pylint: disable=missing-docstring

import atexit
from contextlib import contextmanager
import functools
import logging
import os.path
import shutil
import subprocess
import tempfile
import time

log = logging.getLogger(__name__)


# Helper classes

class MetaNotSet(type):
    def __str__(cls):
        raise ValueError("Value not set in child class")


class NotSet(object):
    __metaclass__ = MetaNotSet


# Dictionary utilities

def merge(dict_a, dict_b):
    """
    Merge two dictionaries.

    Values in `dict_a` take precendence over the ones in `dict_b` unless
    the value in `dict_a` is `None`.

    """
    result = {}
    for key in set(dict_a) | set(dict_b):
        value = dict_a.get(key)
        result[key] = dict_b.get(key) if value is None else value

    return result


def filter_keys(mapping, keys):
    """
    Select only the `keys` in `mapping`. If the key is not in
    `mapping` add an empty entry. If keys is None or empty, select all keys.

    """
    if keys:
        result = {k: {} for k in keys}
        result.update({k: v for k, v
                       in mapping.iteritems()
                       if k in keys})
    else:
        result = mapping.copy()

    return result


# Memoization

def memoize(obj):
    cache = obj.cache = {}

    @functools.wraps(obj)
    def memoizer(*args, **kwargs):
        key = str(args) + str(kwargs)
        if key not in cache:
            cache[key] = obj(*args, **kwargs)
        return cache[key]

    return memoizer


# Temp directories

@contextmanager
def make_temp_directory(suffix='', prefix='tmp', directory=None):
    # create secure temp directory
    temp_dir = tempfile.mkdtemp(suffix, prefix, directory)

    # and delete it at exit
    def clean_dir():
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

    # make sure the directory is deleted, even if interrupted
    atexit.register(clean_dir)

    yield temp_dir

    clean_dir()


def with_temp_directory(*d_args, **d_kwargs):
    """Pass a temp directory to the last argument of a function."""

    def wrap(func):
        @functools.wraps(func)
        def wrapped(*args):
            if func.func_code.co_argcount - len(args) == 1:
                with make_temp_directory(*d_args, **d_kwargs) as temp_dir:
                    args += (temp_dir,)
                    return func(*args)
            else:
                return func(*args)
        return wrapped

    # make the decorator work with or without arguments
    if len(d_args) == 1 and callable(d_args[0]):
        f = d_args[0]
        d_args = []
        return wrap(f)
    else:
        return wrap


# Logging on failures


MEMORY_BUFFER_SIZE = 10 * 1024 * 1024  # 10 MB


@contextmanager
def logging_streams_on_failure(name):
    # Spill to disk if a very large amount of output is generated by the task.
    with tempfile.SpooledTemporaryFile(max_size=MEMORY_BUFFER_SIZE) as error_file:
        with tempfile.SpooledTemporaryFile(max_size=MEMORY_BUFFER_SIZE) as output_file:
            try:
                yield output_file, error_file
            except Exception:
                log.warning('Failed to execute %s', name, exc_info=True)
                log.warning('Standard Output')
                log_file_contents(log.warning, output_file)
                log.warning('Standard Error')
                log_file_contents(log.warning, error_file)
                raise


def log_file_contents(log_func, file_handle):
    file_handle.flush()
    file_handle.seek(0)
    for line in file_handle:
        log_func(line.strip())


# Shell retries


BASE_RETRY_DELAY_IN_SECONDS = 5


def _retry_execute_shell(cmd, attempt, max_tries, **additional_args):
    try:
        return_val = subprocess.check_call(cmd, shell=True, **additional_args)
        return return_val
    except subprocess.CalledProcessError as exception:

        log.exception("Error occurred on attempt %d of %d", attempt, max_tries)

        log.info('DEBUG:::')
        log.info(additional_args['stdout'])
        log.info(type(additional_args['stdout']))
        log.info('stdout_file:::')
        with additional_args'stdout'] as fi:
            for line in fi.readlines():
                log.info(line)
        log.info('stderr_file:::')
        with additional_args'stderr'] as fi:
            for line in fi.readlines():
                log.info(line)




        attempt += 1
        exponential_delay = BASE_RETRY_DELAY_IN_SECONDS * (2 ** attempt)
        log.info("Waiting %d seconds before attempting retry %d", exponential_delay, attempt)
        time.sleep(exponential_delay)

        log.info("Retrying command: attempt %d", attempt)
        if attempt >= max_tries:
            raise
        return _retry_execute_shell(cmd, attempt, max_tries, **additional_args)


def execute_shell(cmd, **kwargs):
    additional_args = {}
    if 'stdout_file' in kwargs:
        additional_args['stdout'] = kwargs['stdout_file']
    if 'stderr_file' in kwargs:
        additional_args['stderr'] = kwargs['stderr_file']

    attempt = 1
    if 'max_tries' in kwargs:
        max_tries = kwargs['max_tries']
    else:
        max_tries = 1

    return _retry_execute_shell(cmd, attempt, max_tries, **additional_args)
