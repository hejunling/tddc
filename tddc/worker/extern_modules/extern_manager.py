# -*- coding: utf-8 -*-
'''
Created on 2017年4月20日

@author: chenyitao
'''

import importlib
import json
import os

from ...log.logger import TDDCLogger
from ...util.util import Singleton
from ..worker_config import WorkerConfigCenter
from ..event import EventType, EventCenter, EventStatus
from ..storager import Storager


class ExternManager(TDDCLogger):
    '''
    classdocs
    '''
    __metaclass__ = Singleton

    def __init__(self):
        EventCenter()
        Storager()
        self.config = WorkerConfigCenter().get_extern_modules_config()
        super(ExternManager, self).__init__()
        self._start()

    def _start(self):
        '''
        Constructor
        '''
        self.info('Extern Modules Is Loading.')
        self._load_local_models()
        self.info('Extern Modules Was Loaded.')

    def _load_local_models(self):
        self._rules_moulds = {}
        conf = WorkerConfigCenter().get_extern_modules()
        if not conf:
            return False
        for platform, packages in conf.items():
            for package in packages:
                try:
                    self._load_moulds(package)
                except Exception as e:
                    self.exception(e)
                    return False
        return True

    @staticmethod
    @EventCenter.route(EventType.ExternModuleUpdate)
    def _models_update_event(event):
        EventCenter().event_status_update(event,
                                          EventStatus.Executed_Success
                                          if ExternManager()._update(event)
                                          else EventStatus.Executed_Failed)

    def _get_remote_config(self, platform):
        success, config = Storager().get(self.config.config_table,
                                         platform,
                                         'config',
                                         'config')
        return json.loads(config.get('config:config')) if success else None

    def _create_package(self, path, platform):
        if not os.path.exists(path):
            os.mkdir(path)
            with open(path + '__init__.py', 'a') as _:
                self.info('Create %s Extern Modules Packages.' % platform)

    def _download_package_file(self, platform, remote_config, path):
        for feature, package in remote_config.items():
            package_package = package.get('package')
            success, package_content = Storager().get(self.config.config_table,
                                                      platform,
                                                      'content',
                                                      package_package)
            if not success:
                return False
            path_base = '%s/%s/' % (path, platform)
            self._create_package(path_base, platform)
            with open(path_base + package.get('package') + '.py', 'w') as f:
                f.write(package_content.get('content:' + package_package))
        return True

    def _update(self, event):
        self.info('Extern Modules Is Updating...')
        platform = event.event.get('platform')
        if not platform:
            return False
        remote_config = self._get_remote_config(platform)
        if not remote_config:
            return False
        path = os.popen('find . -name extern_modules').readlines()[0].strip()
        if not self._download_package_file(platform, remote_config, path):
            return False
        local_config = [type('PackageInfo', (), config) for _, config in remote_config.items()]
        if not WorkerConfigCenter().set_extern_modules(platform, local_config):
            return False
        if not self._load_local_models():
            return False
        self.info('Extern Modules Was Updated.')
        return True

    def _load_moulds(self, package):
        rules_path_base = 'worker.extern_modules'
        try:
            module = importlib.import_module('%s.%s.%s' % (rules_path_base,
                                                           package.platform,
                                                           package.package))
        except Exception as e:
            self.exception(e)
            return False
        if not module:
            return False
        if not self._update_models_table(package.platform, package.mould, module):
            return False
        return True

    def _update_models_table(self, platform, mould, module):
        cls = getattr(module, mould)
        if not cls:
            return False
        feature = cls.__dict__.get('feature', None)
        if not feature:
            return False
        if not self._rules_moulds.get(platform, None):
            self._rules_moulds[platform] = {}
        self._rules_moulds[platform][feature] = cls
        return True

    def get_model(self, platform, feature=None):
        models = self._rules_moulds.get(platform)
        if not models:
            return None
        return models.get(feature) if feature else models

    def get_all_modules(self):
        return self._rules_moulds
