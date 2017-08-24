import argparse
import collections
import pprint
import shutil
import subprocess
import threading
import os
import re
import yaml
from flask import Flask, request
from pyrpm import rpmdefs
from pyrpm.rpm import RPM


class LoggingMiddleware(object):
    def __init__(self, app):
        self._app = app

    def __call__(self, environ, resp):
        errorlog = environ['wsgi.errors']
        pprint.pprint(('REQUEST', environ), stream=errorlog)

        def log_response(status, headers, *args):
            pprint.pprint(('RESPONSE', status, headers), stream=errorlog)
            return resp(status, headers, *args)

        return self._app(environ, log_response)


# def __unicode__(self):
#     return unicode(self.some_field) or u''


def parse_package_info(rpm):
    os_name_rel = rpm[rpmdefs.RPMTAG_RELEASE]
    os_data = re.search('^(\d+)\.(\w+)(\d+)$', os_name_rel)
    package = {
        'filename': "%s-%s-%s.%s.rpm" % (rpm[rpmdefs.RPMTAG_NAME],
                                         rpm[rpmdefs.RPMTAG_VERSION],
                                         rpm[rpmdefs.RPMTAG_RELEASE],
                                         rpm[rpmdefs.RPMTAG_ARCH]),
        'os_abbr': os_data.group(2),
        'os_release': os_data.group(3),
        'os_arch': rpm[rpmdefs.RPMTAG_ARCH]
    }
    return package


app = Flask(__name__)
settings = {}


@app.route('/')
def hello_world():
    return 'Hello from repo!'


@app.route('/upload', methods=['PUT'])
def upload():
    status = 503
    headers = []
    curr_package = request.headers.get('X-Package-Name')
    rpm = RPM(file(unicode(curr_package)))
    rpm_data = parse_package_info(rpm)
    try:
        new_req_queue_element = '%s/%s' % (rpm_data['os_release'], rpm_data['os_arch'])
        dest_dirname = '%s/%s/Packages' % (
            app.settings['repo']['top_dir'],
            new_req_queue_element)
        shutil.move(curr_package, dest_dirname)
        src_filename = '%s/%s' % (dest_dirname, os.path.basename(curr_package))
        dest_filename = '%s/%s' % (dest_dirname, rpm_data['filename'])
        shutil.move(src_filename, dest_filename)
        response = 'OK - Accessible as %s' % dest_filename
        status = 200
        if new_req_queue_element not in req_queue:
            req_queue.append(new_req_queue_element)
        event_timeout.set()
        event_request.set()
    except BaseException as E:
        response = E.message
    return response, status, headers


def update_func(evt_upd, evt_exit):
    """
    Wait for signals from delay thread and main thread. Main thread signals via
    :param evt_exit:
    :return:
    :param evt_upd:
    :return:
    """
    while not evt_exit.is_set():
        if evt_upd.wait():
            curr_elem = req_queue.popleft()
            p = subprocess.Popen([app.settings['index_updater']['executable'],
                                  app.settings['index_updater']['cmdline'],
                                  '%s/%s' % (app.settings['repo']['top_dir'], curr_elem)],
                                 shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            res_stdout, res_stderr = p.communicate(None)
            pprint.pprint(res_stdout)
            pprint.pprint(res_stderr)
            evt_upd.clear()
    return


def update_enable_func(evt_req, evt_tmout, evt_upd, evt_exit):
    while not evt_exit.is_set():
        # wait for request
        evt_req.wait()
        # OK, there's a request
        # Now wait for timer and if someone interrupts - well, leave alone
        while evt_tmout.wait(30) and (not evt_exit.is_set()):
            evt_tmout.clear()
        if evt_exit.is_set():
            break
        evt_upd.set()
        evt_tmout.clear()
        evt_req.clear()
    return


def parse_command_line():
    parser = argparse.ArgumentParser(description='This is a repository update helper')
    parser.prog_name = 'repo_helper'
    parser.add_argument('-c', '--conf', action='store', default='%.yml' % prog_name, type='file', required='false',
                        help='Name of the config file', dest='configfile')
    parser.epilog('This is an example of Nginx configuration:\
  location /repo {\
      alias /srv/repo/storage/;\
      autoindex on;\
  }\
\
  location /upload {\
      proxy_store_access user:rw group:rw all:r;\
      client_body_in_file_only on;\
      client_body_temp_path /tmp/rpms;\
      client_max_body_size 20m;\
      proxy_store on;\
      proxy_http_version 1.1;\
      proxy_temp_path /tmp/rpms;\
      proxy_pass http://localhost:5000;\
      proxy_pass_request_body off;\
      proxy_set_header X-Package-Name $request_body_file;\
  }\
')
    parser.parse_args()
    return parser


def load_config(fn):
    with open(fn, 'r') as f:
        config = yaml.safe_load(f)
    return config


def load_hardcoded_defaults():
    config = {
        'index_updater': {
            'executable': '/bin/createrepo',
            'cmdline': '--update'
        },
        'repo': {
            'top_dir': '/srv/repo/storage'
        },
        'server': {
            'address': '127.0.0.1',
            'port': '5000',
            'prefix_url': 'upload',
            'upload_header': ''
        },
        'log': {
            'name': 'syslog',
            'level': 'INFO'
        }
    }
    return config


if __name__ == '__main__':
    try:
        cli_args = parse_command_line()
        settings = load_config(cli_args['configfile'])
    except BaseException as E:
        settings = load_hardcoded_defaults()
    req_queue = collections.deque()
    # Application-level specific stuff
    # Exit flag
    exit_flag = False
    # Event that signals request arrival
    event_request = threading.Event()
    # Event that signals timeout break
    event_timeout = threading.Event()
    # Event that signals repo update
    event_update = threading.Event()
    # Event that signals finishing of worker threads
    event_exit = threading.Event()
    # Prepare events
    event_request.clear()
    event_timeout.clear()
    event_update.clear()
    # Thread that will wait then start repo indexing process
    update_thread = threading.Thread(name='update_worker', target=update_func, args=(event_update, event_exit))
    update_thread.start()
    # Thread that will wait until delay times out then signal indexing thread
    # If delay is interrupted then it will begin from the start
    delay_thread = threading.Thread(name='delay_worker', target=update_enable_func,
                                    args=(event_request, event_timeout, event_update, event_exit))
    delay_thread.start()
    # Its Majesty Application
    app.wsgi_app = LoggingMiddleware(app.wsgi_app)
    app.run(host=settings['server']['address'], port=settings['server']['port'])
    # This flag will signal both threads to end
    event_exit.clear()

# app.run()
