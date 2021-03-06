# -*- coding: utf-8 -*-
'''
Created on 2017年4月10日

@author: chenyitao
'''
import logging

import gevent
import time
from rediscluster import StrictRedisCluster

log = logging.getLogger(__name__)


class RedisClient(StrictRedisCluster):
    '''
    classdocs
    '''

    def __init__(self, *args, **kwargs):
        self.status = type('RedisStatus', (), {'alive_timestamp': 0})
        super(RedisClient, self).__init__(max_connections=64, *args, **kwargs)
        gevent.spawn(self._alive_check)
        gevent.sleep()

    def redis_info(self, section=None):
        if section is None:
            return self.execute_command('INFO')
        else:
            return self.execute_command('INFO', section)

    def _alive_check(self):
        """
        Redis 存活检测
        """
        while True:
            try:
                if self.ping():
                    self.status.alive_timestamp = int(time.time())
            except Exception as e:
                log.exception(e)
                log.error('Redis Connection Exception.')
            gevent.sleep(5)

    def get_connection_status(self):
        return self.status

    def robust(self, func, *args, **kwargs):
        """
        对命令进行bobust的封装
        :param func:
        :param args:
        :param kwargs:
        :return:
        """
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log.exception(e)
            log.debug('Try Again.')
            if self.connection_pool._created_connections != 0:
                self.connection_pool.reset()
            gevent.sleep(2)
            return self.robust(func, *args, **kwargs)

    def smadd(self, name, values):
        '''
        批量sadd
        '''
        with self.pipeline() as ppl:
            for value in values:
                ppl.sadd(name, value)
            ppl.execute()

    def smpop(self, name, count):
        '''
        批量spop
        '''
        with self.pipeline() as ppl:
            for _ in range(count):
                ppl.spop(name)
            ppl.execute()

    def hmdel(self, name, values):
        '''
        批量hdel
        '''
        with self.pipeline() as ppl:
            for value in values:
                ppl.hdel(name, value)
            ppl.execute()

    def hmove(self, old_name, new_name, key, value):
        with self.pipeline() as ppl:
            if old_name:
                ppl.hdel(old_name, key)
            ppl.hset(new_name, key, value)
            ppl.execute()

    def psubscribe(self, pattern):
        '''
        匹配订阅
        '''
        ps = self.pubsub()
        ps.psubscribe(pattern)
        log.info('Subscribe %s...' % pattern)
        for item in ps.listen():
            yield item
        ps.unsubscribe('spub')
        log.warning('Subscribe Was Exit.')

    def set_the_hash_value_for_the_hash(self, name, key, value_name, value_key, value):
        with self.pipeline() as ppl:
            ppl.hset(value_name, value_key, value)
            ppl.hset(name, key, value_name)
            ppl.execute()

    def get_the_hash_value_for_the_hash(self, name, key, value_key=None):
        value_name = self.hget(name, key)
        value = self.hget(value_name, value_key) if value_key else self.hgetall(value_name)
        return value

    def clean(self, pattern='*'):
        def _clean(_pattern):
            for key in self.keys(pattern):
                self.delete(key)
            else:
                return True
        return self.robust(_clean, pattern)

    @staticmethod
    def timer(seconds, callback, *args, **kwargs):
        def _timer(_callback, *_args, **_kwargs):
            callback(*_args, **_kwargs)

        gevent.spawn_later(seconds, _timer, callback, *args, **kwargs)
        gevent.sleep()
