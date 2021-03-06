#!/usr/bin/env python
"""
    ActiveMQ client for Dakota
"""
import os
import sys
import json
import logging
import argparse
import threading
import time

from sns_utilities.amq_connector.amq_consumer import Client, Listener
from configuration import Configuration

class DakotaListener(Listener):
    """
        ActiveMQ Listener for Dakota
        This class processes incoming messages
    """
    
    def __init__(self, configuration=None, 
                 results_ready_queue=None,
                 catalog_results_ready_queue=None):
        super(DakotaListener, self).__init__(configuration)
        
        self._conf = configuration
        self._connection = None
        self._complete = False
        self._transaction_complete = threading.Condition()
        if results_ready_queue is not None:
            self.results_ready_queue = results_ready_queue
        else:
            self.results_ready_queue = configuration.results_ready_queue
        self.catalog_results_ready_queue = catalog_results_ready_queue

    def on_message(self, headers, message):
        """
            Process a message.
            @param headers: message headers
            @param message: JSON-encoded message content
        """
        if headers['destination']=='/queue/'+self.results_ready_queue:
            
            try:
                data_dict = json.loads(message)
                output_file = data_dict['output_file']
                
                logging.info("Rcv: %s | Output file: %s" % (self.results_ready_queue, output_file))
                
                self._transaction_complete.acquire()
                self._complete = True
                self._transaction_complete.notify()
                self._transaction_complete.release()
            except:
                logging.error("Could not process JSON message")
                logging.error(str(sys.exc_value))
                
            # If we have a cataloging queue, send a message to it
            if self.catalog_results_ready_queue is not None:
                self.send(self.catalog_results_ready_queue, message)

    def wait_on_transaction_complete(self):
        """
            Wait for the results ready message
        """
        self._transaction_complete.acquire()
        while not self._complete == True:
            self._transaction_complete.wait()
        self._transaction_complete.release()
        
    def _disconnect(self):
        """
            Clean disconnect
        """
        if self._connection is not None and self._connection.is_connected():
            self._connection.disconnect()
        self._connection = None

    def get_connection(self):
        """
            Establish and return a connection to ActiveMQ
        """
        logging.info("[Dakota Listener] Attempting to connect to ActiveMQ broker")
        conn = stomp.Connection(host_and_ports=self._conf.brokers, 
                                user=self._conf.amq_user,
                                passcode=self._conf.amq_pwd, 
                                wait_on_receipt=True)
        conn.start()
        conn.connect()
        # Give the connection threads a little breather
        time.sleep(0.5)
        return conn
        
    def send(self, destination, message, persistent='true'):
        """
            Send a message to a queue
            @param destination: name of the queue
            @param message: message content
        """
        if self._connection is None or not self._connection.is_connected():
            self._disconnect()
            self._connection = self.get_connection()
        self._connection.send(destination=destination, message=message, persistent=persistent)
        
        
class DakotaClient(Client):
    """
        ActiveMQ Client for Dakota
        This class hold the connection to ActiveMQ and 
        starts the listening thread.
    """
    ## Input queue used to trigger a new calculation
    params_ready_queue = "PARAMS.READY"
    ## Output queue to announce results
    results_ready_queue = "RESULTS.READY"
    ## Input queue used to catalog input parameters
    catalog_params_ready_queue = "CATALOG_PARAMS.READY"
    ## Output queue to announce results
    catalog_results_ready_queue = "CATALOG_RESULTS.READY"
    
    def set_results_ready_queue(self, queue):
        """ 
            Set the name of the queue to be used to 
            announce new results
            @param queue: name of an ActiveMQ queue
        """
        logging.info("Dakota client will listen for results on %s" % queue)
        self.results_ready_queue = queue
        self.catalog_results_ready_queue = "CATALOG_%s" % self.results_ready_queue
        
    def set_params_ready_queue(self, queue):
        """ 
            Set the name of the queue to be used to 
            request new calculations/simulations
            @param queue: name of an ActiveMQ queue
        """
        logging.info("Dakota client will send parameters to %s" % queue)
        self.params_ready_queue = queue
        self.catalog_params_ready_queue = "CATALOG_%s" % self.params_ready_queue
        
    def set_working_directory(self, working_directory):
        """
            Set the working directory in which Dakota will write
            @param working_directory: directory for dakota to write parameter files
        """
        self.working_directory = working_directory
        
    def listen_and_wait(self, waiting_period=1.0):
        """
            Listen for the next message from the brokers.
            @param waiting_period: sleep time between connection to a broker
        """       
        listening = True
        while(listening):
            try:
                if self._connection is None or self._connection.is_connected() is False:
                    self.connect()                
                time.sleep(waiting_period)
                
                # Wait for the listening thread to receive the results message
                self._listener.wait_on_transaction_complete()
                
                # Once the results message has been received and dealt with,
                # we can simply stop listening
                logging.info("Unsubscribing to %s" % self.results_ready_queue)
                self._connection.unsubscribe(destination=self.results_ready_queue)
                if self._connection.get_listener(self._consumer_name) is not None:
                    logging.info("Removing listener %s" % self._consumer_name)
                    self._connection.remove_listener(self._consumer_name)
                self._connection.stop()
                listening = False
            
            # Catch Ctrl-C for interactive running
            except KeyboardInterrupt:
                sys.exit(0)
            except:
                logging.error("Problem connecting to AMQ broker")
                logging.error("%s: %s" % (sys.exc_type,sys.exc_value))
                time.sleep(5.0)

    def params_ready(self, input_file, output_file):
        """
            Send an ActiveMQ message announcing new
            parameters.
            @param input_file: parameters input file path
            @param output_file: results file to be created
        """
        if os.path.exists(input_file):
            try:
                fd = open(input_file, 'r')
                params = fd.read()
                message = {'params': params,
                           'output_file': output_file,
                           'amq_results_queue': self.results_ready_queue,
                           'working_directory': self.working_directory
                           }
                json_message = json.dumps(message)
                self.send(self.params_ready_queue, json_message)
                self.send(self.catalog_params_ready_queue, json_message)
            except:
                logging.error("Could not read %s file: %s" % (input_file, sys.exc_value))
        else:
            logging.error("Parameter file %s does not exist" % input_file)


def setup_client(instance_number=None, 
                 working_directory=None, 
                 config_file='/etc/kepler_consumer.conf'):
    """
        Create an instance of the Dakota ActiveMQ consumer
        @param instance_number: instance number to use for 
                                transient process communication
        @param working_directory: directory for dakota to write parameter files
        @param config_file: configuration file to use to setup the client
    """
    # Make sure we have an instance number
    if instance_number is None:
        instance_number = os.getppid()
        
    # Determine the working directory
    if working_directory is None:
        working_directory = os.path.expanduser('~')
        
    # Look for configuration
    conf = Configuration(config_file)

    results_queue = "%s.%s" % (conf.results_ready_queue, str(instance_number))
    params_queue = "%s.%s" % (conf.params_ready_queue, str(instance_number))
    queues = [results_queue]
    c = DakotaClient(conf.brokers, conf.amq_user, conf.amq_pwd, 
                     queues, "dakota_consumer.%s" % str(instance_number))
    c.set_params_ready_queue(params_queue)
    c.set_results_ready_queue(results_queue)
    c.set_working_directory(working_directory)
    c.set_listener(DakotaListener(conf, results_ready_queue=results_queue,
                                  catalog_results_ready_queue=c.catalog_results_ready_queue))
    return c
    
    
def run():
    """
        Run an instance of the Dakota ActiveMQ consumer
    """
    
    # Set log level set up log file handler
    logging.getLogger().setLevel(logging.INFO)
    ft = logging.Formatter('%(asctime)-15s %(message)s')
    fh = logging.FileHandler('dakota_client.log')
    fh.setLevel(logging.INFO)
    fh.setFormatter(ft)
    logging.getLogger().addHandler(fh)

    # Get the command line options
    parser = argparse.ArgumentParser(description='Dakota AMQ client')
    parser.add_argument('-c', metavar='configuration',
                        default='/etc/kepler_consumer.conf',
                        help='location of the configuration file',
                        dest='config_file')
    parser.add_argument('-d', metavar='work_directory',
                        default='/tmp',
                        help='location of the working directory',
                        dest='work_directory')
    parser.add_argument('-t',
                        action='store_true',
                        help='test execution',
                        dest='is_test')
    namespace = parser.parse_args()

    c = setup_client(working_directory=namespace.work_directory,
                     config_file=namespace.config_file)
    
    if namespace.is_test is True:
        fd = open(namespace.work_directory+'/test_params.in', 'w')
        fd.write("123.456")
        fd.close()
        c.params_ready(namespace.work_directory+'/test_params.in',
                       namespace.work_directory+'/test_results.out')

    c.listen_and_wait(0.1)

if __name__ == "__main__": 
    run()