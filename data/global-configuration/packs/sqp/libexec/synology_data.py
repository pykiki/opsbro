import os

PY3 = False


# Bytes to unicode
def bytes_to_unicode(s):
    if isinstance(s, str) and not PY3:  # python3 already is unicode in str
        return s.decode('utf8', 'ignore')
    if PY3 and isinstance(s, bytes):
        return s.decode('utf8', 'ignore')
    return s


class SynologyCheck(object):
    oids = {
        
        'model'                  : ("1.3.6.1.4.1.6574.1.5.1.0", None),
        'serialNumber'           : ("1.3.6.1.4.1.6574.1.5.2.0", 'serial'),
        'DSMVersion'             : ("1.3.6.1.4.1.6574.1.5.3.0", 'dsm_version'),
        'DSMUpgradeAvailable'    : ("1.3.6.1.4.1.6574.1.5.4.0", 'dsm_upgrade_available'),
        'systemStatus'           : ("1.3.6.1.4.1.6574.1.1.0", 'system_status'),
        'temperature'            : ("1.3.6.1.4.1.6574.1.2.0", None),
        'powerStatus'            : ("1.3.6.1.4.1.6574.1.3.0", 'power_status'),
        'systemFanStatus'        : ("1.3.6.1.4.1.6574.1.4.1.0", 'system_fan_status'),
        'CPUFanStatus'           : ("1.3.6.1.4.1.6574.1.4.2.0", 'cpu_fan_status'),
        
        'RAIDName'               : ("1.3.6.1.4.1.6574.3.1.1.2", 'raid_name'),
        'RAIDStatus'             : ("1.3.6.1.4.1.6574.3.1.1.3", 'raid_status'),
        
        'UpsModel'               : ("1.3.6.1.4.1.6574.4.1.1.0", 'ups_model'),
        'UpsSN'                  : ("1.3.6.1.4.1.6574.4.1.3.0", 'ups_serial'),
        'UpsStatus'              : ("1.3.6.1.4.1.6574.4.2.1.0", 'ups_status'),
        'UpsLoad'                : ("1.3.6.1.4.1.6574.4.2.12.1.0", 'ups_load'),
        'UpsBatteryCharge'       : ("1.3.6.1.4.1.6574.4.3.1.1.0", 'ups_batterie_charge'),
        'UpsBatteryChargeWarning': ("1.3.6.1.4.1.6574.4.3.1.4.0", 'ups_batterie_warning'),
    }
    
    disks_oids = {
        'diskID'    : "1.3.6.1.4.1.6574.2.1.1.2",
        'diskModel' : "1.3.6.1.4.1.6574.2.1.1.3",
        'diskStatus': "1.3.6.1.4.1.6574.2.1.1.5",
        'diskTemp'  : "1.3.6.1.4.1.6574.2.1.1.6",
        
    }
    
    mappings = {
        'DSMUpgradeAvailable': {
            1: 'available',
            2: 'unavailable',
            3: 'connecting',
            4: 'disconnected',
            5: 'others',
        },
        
        'diskStatus'         : {
            1: "normal",
            2: "initialized",
            3: "notInitialized",
            4: 'systemPartitionFailed',
            5: "crashed",
        },
        
        'RAIDStatus'         : {
            1 : "normal",
            2 : "repairing",
            3 : "migrating",
            4 : "expanding",
            5 : "deleting",
            6 : "creating",
            7 : "raidSyncing",
            8 : "raidParityChecking",
            9 : "raidAssembling",
            10: "canceling",
            11: "degrade",
            12: "crashed",
        },
        
    }
    status_properties = ('systemStatus', 'powerStatus', 'CPUFanStatus', 'systemFanStatus')
    
    status_renaming = {
    
    }
    
    
    def __init__(self):
        self.status = 3
        self.output = ''
        self.perf_datas = []
    
    
    @staticmethod
    def exec_command(cmd):
        import subprocess
        # If we have a list, we should not call with a shell
        shell = False if isinstance(cmd, list) else True
        # close_fds: I used to set True on unix (False on Windows because it do not manage it)
        # but it's just tooooooo cpu consuming, calling 65K time close()
        # so... nop
        close_fds = False
        # There is no setsid function on windows
        preexec_fn = getattr(os, 'setsid', None)
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=close_fds, preexec_fn=preexec_fn, shell=shell)
        stdout, stderr = p.communicate()
        stdout = bytes_to_unicode(stdout)
        stderr = bytes_to_unicode(stderr)
        return p.returncode, stdout, stderr
    
    
    def _parse_line(self, line):
        if line.startswith('STRING:'):
            line = line.replace('STRING:', '')
            line = line.replace('"', '').strip()
            return line
        if line.startswith('INTEGER:'):
            res = line.replace('INTEGER:', '').strip()
            res = int(res)
            return res
        # Do not exist oid
        if 'No Such Instance ' in line:
            return None
        # self.logger.warning('UNKNOWN OID result type: %s' % line)
        return None
    
    
    def _get_transformed_value(self, v, key_name):
        if key_name in self.status_properties:
            if v == 1:
                return 'normal'
            else:
                return 'failed'
        
        mapping_entry = self.mappings.get(key_name, None)
        if mapping_entry:
            return mapping_entry.get(v, 'unknown')
        
        return v
    
    
    def _get_snmp_value(self, oid):
        # IMPORTANT: on synology we only have snmpwalk and not snmpget
        cmd = 'LANG=C snmpwalk -v 2c -c public -O vUE 127.0.0.1 %s' % oid
        
        rc, stdout, stderr = self.exec_command(cmd)
        if rc != 0:
            return None
        # self.logger.debug('GET RES: %s' % out)
        lines = stdout.splitlines()
        if len(lines) >= 2:
            r = []
            for line in lines:
                v = self._parse_line(line)
                if v is not None:
                    r.append(v)
            return r
        
        return self._parse_line(stdout)
    
    
    def get_disks_data(self):
        res = {}
        # Disk ones (we will zip them)
        disk_ids = self._get_snmp_value(self.disks_oids['diskID'])
        disk_models = self._get_snmp_value(self.disks_oids['diskModel'])
        disk_status = self._get_snmp_value(self.disks_oids['diskStatus'])
        disk_temps = self._get_snmp_value(self.disks_oids['diskTemp'])
        
        disks_entry = {}
        
        if disk_ids is not None:
            for (idx, disk_id) in enumerate(disk_ids):
                disk_model = disk_models[idx]
                disk_statu = disk_status[idx]
                final_disk_status = self._get_transformed_value(disk_statu, key_name='diskStatus')
                disk_temp = disk_temps[idx]
                disks_entry[disk_id] = {'model': disk_model, 'status': final_disk_status, 'temperature': disk_temp}
            res['disks'] = disks_entry
        
        other_keys = ('RAIDName', 'RAIDStatus')
        for k in other_keys:
            save_name, value = self._get_data(k)
            res[save_name] = value
        
        return res
    
    
    def _get_data(self, oid_key):
        c = self.oids[oid_key]
        
        oid, name_mapping = c
        # self.logger.debug('GET => %s ' % k)
        v = self._get_snmp_value(oid)
        final_value = self._get_transformed_value(v, key_name=oid_key)
        # Take the name from a mappign if available, else take the raw key name
        saved_name = name_mapping if name_mapping is not None else oid_key
        # self.logger.debug('Get OID %s => %s' % (saved_name, final_value))
        return (saved_name, final_value)
    
    
    def get_hardware_data(self):
        keys = ('systemFanStatus', 'temperature', 'CPUFanStatus', 'UpsStatus', 'powerStatus', 'systemStatus')
        res = {}
        for k in keys:
            save_name, value = self._get_data(k)
            res[save_name] = value
        return res
    
    
    def launch(self):
        meta_data = {}
        
        res = meta_data.copy()
        
        for (k, c) in self.oids.items():
            save_name, value = self._get_data(k)
            res[save_name] = value
        print 'RESULT', res
        for (k, v) in res.iteritems():
            print('%s => %s' % (k, v))
        return res
