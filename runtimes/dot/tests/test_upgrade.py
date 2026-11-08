import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import test_runtime as base

class UpgradeCase(unittest.TestCase):
    setUp=base.RuntimeCase.setUp
    tearDown=base.RuntimeCase.tearDown
    ready=base.RuntimeCase.ready
    def test_running_guest_refused_before_copy_or_mutation(self):
        source=Path(__file__).resolve().parents[1]/'scripts/upgrade_guest.py'
        spec=importlib.util.spec_from_file_location('upgrade_script',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        agent=self.ready();config=Path(self.temp.name)/'config.json';config.write_text(json.dumps(self.config))
        with patch.object(module.Libvirt,'inspect',return_value={'power_state':'running'}),patch.object(module.shutil,'copy2') as copy:
            with self.assertRaises(ValueError):module.upgrade(config,agent['id'])
            copy.assert_not_called()
    def test_active_task_refused_before_hypervisor_access(self):
        source=Path(__file__).resolve().parents[1]/'scripts/upgrade_guest.py'
        spec=importlib.util.spec_from_file_location('upgrade_script_active',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        agent=self.ready();self.runtime.submit(agent['id'],{'prompt':'Active'})
        config=Path(self.temp.name)/'config.json';config.write_text(json.dumps(self.config))
        with patch.object(module.Libvirt,'inspect') as inspect:
            with self.assertRaises(ValueError):module.upgrade(config,agent['id'])
            inspect.assert_not_called()
