This directory is meant to contain Kepler-specific code and configuration for CAMM

## Pre-requisites
- stomp.py should be installed to enable ActiveMQ communication ([http://code.google.com/p/stomppy/](http://code.google.com/p/stomppy/))
	 
## ActiveMQ Consumer Installation
- Run `python setup.py install` in the `activemq` directory.  
The setup.py script will not only install the `amq_kepler` module, but will
also create a script named `kepler_consumer` at a location where it can be
used by all users.  
In the event that the `kepler_consumer` script is not installed on the
system path, you can use the `--install-scripts` option when running 
the installation script:
 
	`python setup.py install --install-scripts /usr/local/bin`
 
- To use the ActiveMQ consumer for Kepler, add an `External Execution` actor
to your workflow and execute `/usr/local/bin/kepler_client` with it.
 
- The Kepler consumer can be configured by adding a file named
`kepler_consumer.conf` in /etc.
The configuration file should be in JSON format and can contain the
following parameters
 

	`
	{  
		"brokers": [["localhost", 61613]],  
		"amq_queues": ["foo.bar"],   
		"amq_user": "icat",  
 		"amq_pwd": "icat" 
 		"params_ready_queue": "MY_DAKOTA_PARAMS_READY_QUEUE",
 		"results_ready_queue": "MY_DAKOTA_RESULTS_READY_QUEUE",
	}
	`
 
## Using the Kepler Client
An example Kepler Client can be found in `activemq/kepler_client.py`.
In this example, the client listens to messages from the `params_ready_queue`.
Upon receiving such a message, it resends it after having added an entry
with the evaluated cost function for the input parameters.

To start the Kepler client, just type `kepler_client`

## Using the Dakota Client
The `dakota/examples` directory contains the `python_driver_example.in` Dakota file.
It uses an `opt_driver` that simply executes the `optimization_driver.py` script,
which sends an ActiveMQ message announcing new parameters and waits for a
message announcing that results are ready.

To start the Dakota example and have it communicate with Kepler, just do the
following after having started the Kepler client:

	`dakota.sh -i python_driver_example.in`

