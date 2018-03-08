import os
import time
import traceback
import random
import threading
import glob
import imp
import copy
import json

from .log import LoggerFactory
from .threadmgr import threader
from .stop import stopper
from .httpdaemon import http_export, response
from .collector import Collector
from jsonmgr import jsoner
from .now import NOW
from .ts import tsmgr
from .gossip import gossiper
from .util import make_dir

# Global logger for this part
logger = LoggerFactory.create_logger('collector')


def get_collectors(self):
    collector_dir = os.path.dirname(__file__)
    p = collector_dir + '/collectors/*py'
    logger.debug('Loading collectors from path:', p)
    collector_files = glob.glob(p)
    for f in collector_files:
        fname = os.path.splitext(os.path.basename(f))[0]
        try:
            imp.load_source('collector%s' % fname, f)
        except Exception, exp:
            logger.error('Cannot load collector %s: %s' % (fname, exp))
            continue
    
    self.load_all_collectors()


class CollectorManager:
    def __init__(self):
        self.collectors = {}
        
        self.did_run = False  # did our data are all ok or we did not launch all?
        
        # results from the collectors, keep ony the last run
        self.results_lock = threading.RLock()
        self.results = {}
        
        self.history_directory = None
        self.__current_history_entry = []
        self.__current_history_entry_lock = threading.RLock()
    
    
    def load_directory(self, directory, pack_name='', pack_level=''):
        logger.debug('Loading collector directory at %s for pack %s' % (directory, pack_name))
        pth = directory + '/collector_*.py'
        collector_files = glob.glob(pth)
        for f in collector_files:
            fname = os.path.splitext(os.path.basename(f))[0]
            logger.debug('Loading collector from file %s' % f)
            try:
                # NOTE: KEEP THE ___ as they are used to let the class INSIDE te module in which pack/level they are. If you have
                # another way to give the information to the inner class inside, I take it ^^
                m = imp.load_source('collector___%s___%s___%s' % (pack_level, pack_name, fname), f)
                logger.debug('Collector module loaded: %s' % m)
            except Exception, exp:
                logger.error('Cannot load collector %s: %s' % (fname, exp))
    
    
    def load_all_collectors(self):
        collector_clss = Collector.get_sub_class()
        for ccls in collector_clss:
            # skip base module Collector
            if ccls == Collector:
                continue
            
            # Maybe this collector is already loaded
            if ccls in self.collectors:
                continue
            
            self.load_collector(ccls)
    
    
    def load_collector(self, cls):
        colname = cls.__name__.lower()
        
        # If already loaded, skip it
        if colname in self.collectors:
            return
        
        logger.debug('Loading collector %s from class %s, from pack %s and from pack level %s' % (colname, cls, cls.pack_name, cls.pack_level))
        try:
            # also give it our put result callback
            inst = cls()
        except Exception, exp:
            logger.error('Cannot load the %s collector: %s' % (cls, traceback.format_exc()))
            return
        
        e = {
            'name'      : colname,
            'inst'      : inst,
            'last_check': 0,
            'next_check': int(time.time()) + int(random.random()) * 10,
            'results'   : None,
            'metrics'   : None,
            'active'    : False,
            'log'       : '',
        }
        self.collectors[colname] = e
    
    
    # Now we hae our collectors and our parameters, link both
    def get_parameters_from_packs(self):
        for (cname, e) in self.collectors.iteritems():
            e['inst'].get_parameters_from_pack()
    
    
    def load_collectors(self):
        get_collectors(self)
    
    
    def get_info(self):
        res = {}
        with self.results_lock:
            for (cname, e) in self.collectors.iteritems():
                d = {'name': e['name'], 'active': e['active'], 'log': e['log']}
                res[cname] = d
        return res
    
    
    def get_retention(self):
        res = {}
        with self.results_lock:
            for (cname, e) in self.collectors.iteritems():
                res[cname] = {}
                res[cname]['results'] = e['results']
                res[cname]['metrics'] = e['metrics']
                res[cname]['state'] = e['inst'].state
                res[cname]['old_state'] = e['inst'].old_state
        return res
    
    
    def load_retention(self, data):
        with self.results_lock:
            for (cname, e) in data.iteritems():
                # maybe this collectr is missing now
                if cname not in self.collectors:
                    continue
                inst = self.collectors[cname]['inst']
                self.collectors[cname]['results'] = e['results']
                self.collectors[cname]['metrics'] = e['metrics']
                inst.state = e.get('state', 'PENDING')
                inst.old_state = e.get('old_state', 'PENDING')
    
    
    def get_data(self, s):
        elts = s.split('.')
        d = {}
        # construct will all results of our collectors
        for (k, v) in self.collectors.iteritems():
            d[k] = v['results']
        
        for k in elts:
            if not isinstance(d, dict) or k not in d:
                raise KeyError('Cannot find %s key %s in %s' % (s, k, elts))
            d = d[k]
        # last is the good one
        return d
    
    
    # Our collector threads will put back results so beware of the threads
    def put_result(self, cname, results, metrics, log):
        logger.debug('[COLLECTOR] put result for %s: %s metrics' % (cname, len(metrics)), part='collector.%s' % cname)
        col = self.collectors.get(cname, None)
        
        # Maybe there is no more such collector?
        if col is None:
            return
        col = self.collectors[cname]
        col['log'] = log
        
        # Only set results and metrics if available
        if not results:
            col['active'] = False
            return
        
        col['results'] = results
        col['metrics'] = metrics
        col['active'] = True
        
        timestamp = NOW.now
        for (mname, value) in metrics:
            key = '%s.%s.%s' % (gossiper.name, cname, mname)
            if hasattr(tsmgr, 'tsb'):
                tsmgr.tsb.add_value(timestamp, key, value, local=True)
    
    
    def __prepare_history_directory(self):
        # Prepare the history
        from .configurationmanager import configmgr
        data_dir = configmgr.get_data_dir()
        self.history_directory = os.path.join(data_dir, 'collector_history')
        logger.debug('Asserting existence of the collector history directory: %s' % self.history_directory)
        if not os.path.exists(self.history_directory):
            make_dir(self.history_directory)
    
    
    def add_history_entry(self, history_entry):
        with self.__current_history_entry_lock:
            self.__current_history_entry.append(history_entry)
    
    
    def __write_history_entry(self):
        # Noting to do?
        if not self.__current_history_entry:
            return
        # We must lock because checks can exit in others threads
        with self.__current_history_entry_lock:
            now = int(time.time())
            pth = os.path.join(self.history_directory, '%d.json' % now)
            logger.info('Saving new collector history entry to %s' % pth)
            buf = json.dumps(self.__current_history_entry)
            with open(pth, 'w') as f:
                f.write(buf)
            # Now we can reset it
            self.__current_history_entry = []
    
    
    def get_history(self):
        r = []
        current_size = 0
        max_size = 1024 * 1024
        reg = self.history_directory + '/*.json'
        history_files = glob.glob(reg)
        # Get from the more recent to the older
        history_files.sort()
        history_files.reverse()
        
        # Do not send more than 1MB, but always a bit more, not less
        for history_file in history_files:
            epoch_time = int(os.path.splitext(os.path.basename(history_file))[0])
            with open(history_file, 'r') as f:
                e = json.loads(f.read())
            r.append({'date': epoch_time, 'entries': e})
            
            # If we are now too big, return directly
            size = os.path.getsize(history_file)
            current_size += size
            if current_size > max_size:
                # Give older first
                r.reverse()
                return r
        # give older first
        r.reverse()
        return r
    
    
    # Main thread for launching collectors
    def do_collector_thread(self):
        logger.log('COLLECTOR thread launched')
        cur_launchs = {}
        # Before run, be sure we have a history directory ready
        self.__prepare_history_directory()
        while not stopper.interrupted:
            now = int(time.time())
            for (colname, e) in self.collectors.iteritems():
                colname = e['name']
                inst = e['inst']
                # maybe a collection is already running
                if colname in cur_launchs:
                    continue
                if now >= e['next_check']:
                    logger.debug('COLLECTOR: launching collector %s' % colname)
                    t = threader.create_and_launch(inst.main, name='collector-%s' % colname, part='collector')
                    cur_launchs[colname] = t
                    e['next_check'] += 10
                    e['last_check'] = now
            
            to_del = []
            for (colname, t) in cur_launchs.iteritems():
                # if the thread is finish, join it
                # NOTE: but also wait for all first execution to finish
                if not t.is_alive() or not self.did_run:
                    logger.debug('Joining collector thread: %s' % colname)
                    t.join()
                    to_del.append(colname)
            for colname in to_del:
                del cur_launchs[colname]
            self.did_run = True  # ok our data are filled, you can use this data
            # Each loop we save our history data (collector state changed)
            self.__write_history_entry()
            time.sleep(1)
    
    
    def get_collector_json_extract(self, entry):
        c = copy.copy(entry)
        inst = c['inst']
        c['state'] = inst.state
        c['log'] = inst.log
        # inst are not serializable
        del c['inst']
        return (c['name'], c)
    
    
    # main method to export http interface. Must be in a method that got
    # a self entry
    def export_http(self):
        
        @http_export('/collectors/')
        @http_export('/collectors')
        #        @protected()
        def GET_collectors():
            response.content_type = 'application/json'
            res = {}
            for (ccls, e) in self.collectors.iteritems():
                cname, c = self.get_collector_json_extract(e)
                res[cname] = c
            return jsoner.dumps(res)
        
        
        @http_export('/collectors/:_id')
        def GET_collector(_id):
            response.content_type = 'application/json'
            e = self.collectors.get(_id, None)
            if e is None:
                return jsoner.dumps(e)
            cname, c = self.get_collector_json_extract(e)
            return jsoner.dumps(c)
        
        
        @http_export('/agent/collectors/history', method='GET')
        def get_collectors_history():
            response.content_type = 'application/json'
            r = self.get_history()
            return json.dumps(r)


collectormgr = CollectorManager()
