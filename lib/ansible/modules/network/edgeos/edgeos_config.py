#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2018 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = """
---
module: edgeos_config
version_added: "2.5"
author:
    - "Nathaniel Case (@Qalthos)"
    - "Sam Doran (@samdoran)"
short_description: Manage EdgeOS configuration on remote device
description:
  - This module provides configuration file management of EdgeOS
    devices. It provides arguments for managing both the
    configuration file and state of the active configuration. All
    configuration statements are based on `set` and `delete` commands
    in the device configuration.
  - "This is a network module and requires the C(connection: network_cli) in
    order to work properly."
  - For more information please see the
    L(Network Guide,../network/getting_started/index.html).
notes:
  - Tested against EdgeOS v2.0.8
  - Setting C(ANSIBLE_PERSISTENT_COMMAND_TIMEOUT) to 30 is recommended since
    the save command can take longer than the default of 10 seconds on
    some EdgeOS hardware.
options:
  lines:
    description:
      - The ordered set of configuration lines to be managed and
        compared with the existing configuration on the remote
        device.
  src:
    description:
      - The C(src) argument specifies the path to the source config
        file to load. The source config file can either be in
        bracket format or set format. The source file can include
        Jinja2 template variables.
  match:
    description:
      - The C(match) argument controls the method used to match
        against the current active configuration. By default, the
        desired config is matched against the active config and the
        deltas are loaded. If the C(match) argument is set to C(none)
        the active configuration is ignored and the configuration is
        always loaded.
    default: line
    choices: ['line', 'none']
  backup:
    description:
      - The C(backup) argument will backup the current device's active
        configuration to the Ansible control host prior to making any
        changes. If the C(backup_options) value is not given, the backup
        file will be located in the backup folder in the playbook root
        directory or role root directory if the playbook is part of an
        ansible role. If the directory does not exist, it is created.
    type: bool
    default: 'no'
  comment:
    description:
      - Allows a commit description to be specified to be included
        when the configuration is committed. If the configuration is
        not changed or committed, this argument is ignored.
    default: 'configured by edgeos_config'
  config:
    description:
      - The C(config) argument specifies the base configuration to use
        to compare against the desired configuration. If this value
        is not specified, the module will automatically retrieve the
        current active configuration from the remote device.
  save:
    description:
      - The C(save) argument controls whether or not changes made
        to the active configuration are saved to disk. This is
        independent of committing the config. When set to C(True), the
        active configuration is saved.
    type: bool
    default: 'no'
  delete_unmanaged:
    description:
      - The C(delete_unmanaged) argument controls whether or not unmanaged
        configuration lines are deleted. When set to C(True), the config found
        on the remote device which is not matched in the passed lines of config
        will be added to the updates list as delete commands.
    type: bool
    default: 'no'
    version_added: "2.10"
  backup_options:
    description:
      - This is a dict object containing configurable options related to backup
        file path. The value of this option is read only when C(backup) is set
        to I(yes), if C(backup) is set to I(no) this option will be silently
        ignored.
    suboptions:
      filename:
        description:
          - The filename to be used to store the backup configuration. If the
            filename is not given it will be generated based on the hostname,
            current time and date in format defined by
            <hostname>_config.<current-date>@<current-time>
      dir_path:
        description:
          - This option provides the path ending with directory name in which
            the backup configuration file will be stored. If the directory does
            not exist it will be first created and the filename is either the
            value of C(filename) or default filename as described in
            C(filename) options description. If the path value is not given in
            that case a I(backup) directory will be created in the current
            working directory and backup configuration will be copied in
            C(filename) within I(backup) directory.
        type: path
    type: dict
    version_added: "2.8"
"""

EXAMPLES = """
- name: configure the remote device
  edgeos_config:
    lines:
      - set system host-name {{ inventory_hostname }}
      - set service lldp
      - delete service dhcp-server

- name: backup and load from file
  edgeos_config:
    src: edgeos.cfg
    backup: yes

- name: configurable backup path
  edgeos_config:
    src: edgeos.cfg
    delete_unmanaged: no
    backup: yes
    backup_options:
      filename: backup.cfg
      dir_path: /home/user
"""

RETURN = """
commands:
  description: The list of configuration commands sent to the device
  returned: always
  type: list
  sample: ['...', '...']
invalid:
  description: The list of configuration commands removed for being invalid
  returned: always
  type: list
  sample: ['...', '...']
unmanaged:
  description: The list of configuration commands on the remote device not matching the list provided
  returned: always
  type: list
  sample: ['...', '...']
backup_path:
  description: The full path to the backup file
  returned: when backup is yes
  type: str
  sample: /playbooks/ansible/backup/edgeos_config.2016-07-16@22:28:34
"""

import re

from ansible.module_utils._text import to_native
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.network.common.config import NetworkConfig
from ansible.module_utils.network.edgeos.edgeos import load_config, get_config, run_commands


DEFAULT_COMMENT = 'configured by edgeos_config'


def config_to_commands(config):
    """Parse config depending on form and returns a list of commands

    Only supports `set` and `delete` verbs

    Supports a list of commands or a bracket based configuration file. When
    passing a bracket based config it will parse into a list of set commands.

    :param config: current config from the edgeos device
    :type config: list
    :return: filtered list of config starting with 'set' or 'delete'
    :rtype: list
    """
    set_format = config.startswith('set') or config.startswith('delete')
    candidate = NetworkConfig(indent=4, contents=config)
    if not set_format:
        candidate = [c.line for c in candidate.items]
        commands = list()
        # this filters out less specific lines
        for item in candidate:
            for index, entry in enumerate(commands):
                if item.startswith(entry):
                    del commands[index]
                    break
            commands.append(item)

        commands = ['set %s' % cmd.replace(' {', '') for cmd in commands]

    else:
        commands = to_native(candidate).split('\n')

    return commands


def get_candidate(module):
    """Prepare passed ansible config for diff

    :param module: ansible module for this type (edgeos)
    :type module: ansible.module
    :return contents: list of commands as potential updates
    :rtype: list
    """
    contents = module.params['src'] or module.params['lines']

    if module.params['lines']:
        contents = '\n'.join(contents)

    return config_to_commands(contents)


def diff_config(commands, config):
    """Diff the candidate commands against current config returning lists for
    updates, unmanaged and invalid.

    :param commands: commands provided at ansible runtime
    :type commands: list
    :param config: [commands pulled from edgeos device]
    :type config: list
    :return: updates: changes to apply to remote device
    :rtype: list
    :return: unmanaged_config: config on device without matching candidate
    commands passed to ansible
    :rtype: list
    :return: invalid: commands passed to ansible not starting with 'set' or
    'delete' and therefore considered invalid
    :rtype: list
    """
    config = [to_native(c).replace("'", '') for c in config.splitlines()]

    set_commands, delete_commands, invalid_commands = list(), list(), list()
    updates, unmanaged_config = list(), list()

    for line in commands:
        line = to_native(line).replace("'", '')
        if line.startswith('delete '):
            delete_commands.append(line)
        elif line.startswith('set '):
            set_commands.append(line)
        else:
            invalid_commands.append(line)

    # Will always run the delete commands first to allow for resets
    if delete_commands:
        updates = delete_commands

    # Removing all matching commands already in config
    updates = updates + [line for line in set_commands if line not in config]

    # Add back changes where a corresponding delete command exists
    if delete_commands:
        for line in set_commands:
            search = re.sub('^set ', 'delete ', line)
            for dline in delete_commands:
                if search.startswith(dline):
                    updates.append(line)

    # Unmanaged config (config without matching commands)
    unmanaged_config = (list(set(config) - set(set_commands)))
    matches = list()
    # Remove if actually a change to config
    for line in unmanaged_config:
        search = line.rsplit(' ', 1)[0]
        for update in updates:
            if update.startswith(search):
                matches.append(line)
                break

    unmanaged_config = [line for line in unmanaged_config if line not in matches]

    return updates, unmanaged_config, invalid_commands


def delete_unmanaged(updates, unmanaged):
    """Converts the list of unmanged config found on edgeos device to delete
    commands and adds to the updates list.

    :param updates: list of updates to be made to the edgeos device
    :type updates: list
    :param unmanaged: list of unmanged commands found on the edgeos device
    :type unmanaged: list
    """
    for line in unmanaged:
        nline = re.sub('^set ', 'delete ', line)
        updates.append(nline)


def run(module, result):
    """compares config against passed configuration to asnible to create an
    update list and applies to the edgeos device.

    .. warning:: docstring added long after code written, requires verification
    of Arguments and Returns - please update if you see any errors

    :param module: ansible module for self ref
    :type module: ansible.module
    :param result: result dict to be populated
    process
    :type result: dict
    """

    # get the current active config from the node or passed in via
    # the config param
    config = module.params['config'] or get_config(module)

    # create the candidate config object from the arguments
    candidate = get_candidate(module)

    # create loadable config from updates, also return unmanaged and invalid
    # commands
    updates, unmanaged_config, invalid_commands = diff_config(candidate, config)

    # if delete_unmanaged set, set all all unmanaged commands to delete.
    if unmanaged_config and module.params['delete_unmanaged']:
        delete_unmanaged(updates, unmanaged_config)

    result['commands'] = updates
    result['unmanaged'] = sorted(unmanaged_config)
    result['invalid'] = sorted(invalid_commands)

    commit = not module.check_mode
    comment = module.params['comment']

    if result.get('commands'):
        load_config(module, updates, commit=commit, comment=comment)
        result['changed'] = True

    if result.get('unmanaged'):
        result['warnings'].append('Some configuration commands were '
                                  'unmanaged, review unmanaged list')

    if result.get('invalid'):
        result['warnings'].append('Some configuration commands were '
                                  'invalid, review invalid list')


def main():
    """Sets up module before running changes, applies save of state if
    changed.
    """

    backup_spec = dict(
        filename=dict(),
        dir_path=dict(type='path')
    )
    spec = dict(
        src=dict(type='path'),
        lines=dict(type='list'),

        match=dict(default='line', choices=['line', 'none']),

        comment=dict(default=DEFAULT_COMMENT),

        config=dict(),

        backup=dict(type='bool', default=False),
        backup_options=dict(type='dict', options=backup_spec),
        delete_unmanaged=dict(type='bool', default=False),
        save=dict(type='bool', default=False),
    )

    mutually_exclusive = [('lines', 'src')]

    module = AnsibleModule(
        argument_spec=spec,
        mutually_exclusive=mutually_exclusive,
        supports_check_mode=True
    )

    warnings = list()

    result = dict(changed=False, warnings=warnings)

    if module.params['backup']:
        result['__backup__'] = get_config(module=module)

    if any((module.params['src'], module.params['lines'])):
        run(module, result)

    if module.params['save']:
        diff = run_commands(module, commands=['configure', 'compare saved'])[1]
        if diff != '[edit]':
            run_commands(module, commands=['save'])
            result['changed'] = True
        run_commands(module, commands=['exit'])

    module.exit_json(**result)


if __name__ == '__main__':
    main()
