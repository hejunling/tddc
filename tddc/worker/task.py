# -*- coding: utf-8 -*-
'''
Created on 2017年4月14日

@author: chenyitao
'''

import json

import gevent.queue

from ..log.logger import TDDCLogger
from ..util.util import Singleton, object2json

from .worker_config import WorkerConfigCenter
from .status import StatusManager
from .message_queue import MessageQueue


class TaskStatus(object):
    CrawlTopic = 0

    WaitCrawl = 1
    CrawledSuccess = 200
    # CrawledFailed : 错误码为HTTP Response Status

    WaitParse = 1001
    ParseModuleNotFound = 1100
    ParsedSuccess = 1200
    ParsedFailed = 1400

    @classmethod
    def next_status(cls, state):
        status = [cls.CrawlTopic,
                  cls.WaitCrawl,
                  cls.CrawledSuccess,
                  cls.WaitParse,
                  cls.ParseModuleNotFound,
                  cls.ParsedSuccess,
                  cls.ParsedFailed]
        index = status.index(state)
        if index < 0:
            return cls.WaitCrawl
        if index == len(status) - 1:
            return cls.ParsedFailed
        return status[index + 1]


class Task(object):

    timestamp = 0

    interval = 120

    cur_status = 0

    pre_status = 0

    platform = None

    feature = None

    url = None


class TaskManager(MessageQueue, TDDCLogger):
    '''
    classdocs
    '''
    __metaclass__ = Singleton

    def __init__(self):
        '''
        Constructor
        '''
        TDDCLogger.__init__(self)
        self.task_conf = WorkerConfigCenter().get_task()
        super(TaskManager, self).__init__()
        self.info('Task Manager Is Starting.')
        self._totals = 0
        self._minutes = 0
        self._success = 0
        self._one_minute_past_success = 0
        self._failed = 0
        self._one_minute_past_failed = 0
        self._q = gevent.queue.Queue()
        gevent.spawn(self._counter)
        gevent.sleep()
        gevent.spawn(self._pull)
        gevent.sleep()
        self.info('Task Manager Was Ready.')

    def _counter(self):
        fmt = ('\n'
               '********* Task Status *********\n'
               '-> Totals: %d\n'
               '-> Average: %d\n'
               '-> Success: %d\n'
               '-> OneMinutePastSuccess: %d\n'
               '-> Failed: %d\n'
               '-> OneMinutePastFailed: %d\n'
               '*******************************\n')
        one_minute_past_status = tuple()
        while True:
            gevent.sleep(60)
            current_status = (self._totals,
                              self._success,
                              self._failed)
            if one_minute_past_status == current_status:
                continue
            one_minute_past_status = current_status
            self._minutes += 1
            self.info(fmt % (self._totals,
                             (self._success + self._failed) / (self._minutes if self._minutes != 0 else 1),
                             self._success,
                             self._one_minute_past_success,
                             self._failed,
                             self._one_minute_past_failed))
            self._one_minute_past_success = 0
            self._one_minute_past_failed = 0

    def _pull(self):
        while True:
            if self._q.qsize() < self.task_conf.local_task_queue_size:
                items = self.pull(self.task_conf.consumer_topic,
                                  self.task_conf.local_task_queue_size)
                if not items:
                    gevent.sleep(2)
                    continue
                tasks = [self._record_fetched(item) for item in items]
                tasks = [task for task in tasks if task]
                for task in tasks:
                    self._q.put(task)
                self.info('Pulled New Task(%d).' % len(tasks))
                gevent.sleep(2)
            else:
                gevent.sleep(2)

    def _record_fetched(self, item):
        task = self._deserialization(item)
        if not task:
            self.warning('Task:%s Exception.' % item)
            return None
        task.pre_status = task.cur_status
        task.cur_status = (TaskStatus.WaitCrawl
                           if task.cur_status == TaskStatus.CrawlTopic
                           else TaskStatus.WaitParse)
        self.task_status_changed(task)
        self._totals += 1
        return task

    def _deserialization(self, item):
        try:
            item = json.loads(item)
        except Exception as e:
            self.warning('Task:%s Exception(%s).' % (item, e.message))
            return None
        if not item.get('id') \
                or item.get('cur_status', None) is None \
                or not item.get('platform') \
                or not item.get('feature') \
                or not item.get('url'):
            return None
        return type('TaskRecord', (Task,), item)

    def get(self, block=True, timeout=None):
        task = self._q.get(block, timeout)
        return task

    def task_status_changed(self, task):
        StatusManager().update_status('{base}:{platform}'.format(base=self.task_conf.status_key_base,
                                                                 platform=task.platform),
                                      task.id,
                                      task.cur_status,
                                      task.pre_status)

    def task_successed(self, task):
        self._success += 1
        self._one_minute_past_success += 1
        self.task_status_changed(task)
        self.debug('[%s:%s:%s] Task Success.' % (task.platform,
                                                 task.id,
                                                 task.url))

    def task_failed(self, task):
        self._failed += 1
        self._one_minute_past_failed += 1
        self.task_status_changed(task)
        self.warning('[%s:%s:%s] Task Failed(%d).' % (task.platform,
                                                      task.id,
                                                      task.url,
                                                      task.cur_status))

    def push_task(self, task, topic, status_update=True):
        def _pushed(_):
            if status_update:
                self.task_status_changed(task)
            self.debug('[%s:%s] Pushed(Topic:%s).' % (task.platform,
                                                      task.id,
                                                      topic))

        self.push(self.task_conf.producer_topic, object2json(task), _pushed)
