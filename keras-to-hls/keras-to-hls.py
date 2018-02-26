import numpy as np
import h5py
import os
import tarfile
import json
import argparse
import yaml
import sys
from shutil import copyfile
import math

filedir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,os.path.join(filedir, "..", "hls-writer"))
from hls_writer import hls_writer

#######################################
## Config module
#######################################
def parse_config(config_file) :

    print "Loading configuration from " + str(config_file)
    config = open(config_file, 'r')
    return yaml.load(config)

#######################################
## Print a bias or weight array to C++
#######################################
class print_precision(float):
    def __str__(self):
        return "%.32f"%self

def print_array_to_cpp(name, a, odir ):

    #count zeros
    zero_ctr = 0
    for x in np.nditer(a, order='C'):
        if x == 0: 
            zero_ctr += 1

    #put output in subdir for tarballing later
    f=open("{}/firmware/weights/{}.h".format(odir,name),"w")

    #meta data
    f.write("//Numpy array shape {}\n".format(a.shape))
    f.write("//Min {}\n".format(np.min(a)))
    f.write("//Max {}\n".format(np.max(a)))
    f.write("//Number of zeros {}\n".format(zero_ctr))
    f.write("\n")
    
    #c++ variable 
    if "w" in name: 
        f.write("weight_default_t {}".format(name))
    elif "b" in name: 
        f.write("bias_default_t {}".format(name))
    else:
        raise Exception('ERROR: Unkown weights type')

    #hls doesn't like 3d arrays... unrolling to 1d
    if len(a.shape)>=3: 
        f.write("[{}]".format(np.prod(a.shape)))
    else:
        for x in a.shape:
            f.write("[{}]".format(x))
    f.write(" = {")
    
    #fill c++ array.  
    #not including internal brackets for multidimensional case
    i=0
    for x in np.nditer(a, order='C'):
        if i==0:
#            f.write("{}".format(print_precision(x)))
            f.write("{}".format("%.32f"%x))
        else:
#            f.write(", {}".format(print_precision(x)))
            f.write(", {}".format("%.32f"%x))
        i=i+1
    f.write("};\n")
    f.close()

    return zero_ctr

############################################################################################
## M A I N
############################################################################################
def main():

    # Parse command line arguments
    parser = argparse.ArgumentParser(description='')
    parser.add_argument("-c", action='store', dest='config',
                        help="Configuration file.")
    args = parser.parse_args()
    if not args.config: parser.error('A configuration file needs to be specified.')

    configDir  = os.path.abspath(os.path.dirname(args.config))
    yamlConfig = parse_config(args.config)
    if not os.path.isabs(yamlConfig['OutputDir']):
        yamlConfig['OutputDir'] = os.path.join(configDir, yamlConfig['OutputDir'])
    if not os.path.isabs(yamlConfig['KerasH5']):
        yamlConfig['KerasH5'] = os.path.join(configDir, yamlConfig['KerasH5'])
    if not os.path.isabs(yamlConfig['KerasJson']):
        yamlConfig['KerasJson'] = os.path.join(configDir, yamlConfig['KerasJson'])

    if not (yamlConfig["IOType"] == "io_parallel" or yamlConfig["IOType"] == "io_serial"): 
        raise Exception('ERROR: Invalid IO type')

    ######################
    ##  Do translation
    ######################
    if not os.path.isdir("{}/firmware/weights".format(yamlConfig['OutputDir'])):
        os.makedirs("{}/firmware/weights".format(yamlConfig['OutputDir']))

    h5File = h5py.File( yamlConfig['KerasH5'] )

    #This is a list of dictionaries to hold all the layer info we need to generate HLS
    layer_list = []

    #Extract model architecture from json
    with open( yamlConfig['KerasJson'] ) as json_file:
        model_arch = json.load(json_file)
    #print(model_arch)

    #Define supported laers
    supported_layers = ['InputLayer','Dropout', 'Flatten', 'Dense', 'Conv1D']

    #Define layers to skip for conversion to HLS
    skip_layers = ['InputLayer','Dropout', 'Flatten'] 

    #Loop through layers
    layer_counter = 0
    input_layer = {}

    layer_config = None
    if model_arch['class_name'] == 'Sequential':
        print 'Interpreting Sequential'
        layer_config = model_arch["config"]
    elif model_arch['class_name'] == 'Model':
        print 'Interpreting Model'
        layer_config = model_arch["config"]["layers"]

    # Get input shape and check for unsupported layer type
    current_shape = None
    for keras_layer in layer_config:
        if keras_layer["class_name"] not in supported_layers:
            raise Exception('ERROR: Unsupported layer type: %s'%keras_layer["class_name"])            
        if 'batch_input_shape' in keras_layer['config']:
            current_shape = keras_layer['config']['batch_input_shape'] # [None, 100, 7]    
    print 'Input shape:', current_shape

    print 'Topology:' 
    for keras_layer in layer_config:
        if keras_layer["class_name"] is 'Flatten':
            current_shape = [current_shape[0], np.prod(current_shape[1:])]
        if keras_layer["class_name"] in skip_layers:
            continue 

        layer_counter = layer_counter+1

        #Dictionary to fill in and append to layer_list
        layer = {}

        #Extract name for finding weights and biases
        layer['name']=keras_layer['config']['name']
        layer['class_name']=keras_layer['class_name']

        #Extract type of activation and number of nodes
        for config,config_value in keras_layer["config"].items():
            if(config=="activation"):
                layer['activation']=config_value
            #if(config=="units"):
                #print("PARSED NUM OF NODES",config_value)

        #Translate weights and biases from h5 file
        weights = h5File['/{}/{}/kernel:0'.format(layer['name'],layer['name'])][()]
        biases = h5File['/{}/{}/bias:0'.format(layer['name'],layer['name'])][()]
        cur_n_zeros = print_array_to_cpp("w{}".format(layer_counter), weights, yamlConfig['OutputDir'])
        print_array_to_cpp("b{}".format(layer_counter), biases, yamlConfig['OutputDir'])
        layer['weights_n_zeros'] = cur_n_zeros 

        #Get number of inputs and outputs
        #(We take it from the weights to avoid dealing with InputLayer and Flatten details)
        if layer['class_name']=='Dense':
            layer['n_in']=weights.shape[0]
            layer['n_out']=weights.shape[1]
            current_shape = [current_shape[0], layer['n_out']]
        elif layer['class_name']=='Conv1D':
            # weights.shape = (filter_width, n_channels, n_filters)
            layer['y_in']=current_shape[1]
            layer['y_filt']=weights.shape[0] # or keras_layer['config']['kernel_size']
            layer['n_chan']=weights.shape[1] 
            layer['n_filt']=weights.shape[2] # or keras_layer['config']['filters']
            layer['stride']=keras_layer['config']['strides'][0]
            layer['padding']=keras_layer['config']['padding']
            if layer['padding']=='same':
                in_width = current_shape[1]
                layer['y_out'] = int(math.ceil(float(in_width) / float(layer['stride'])))
                if (in_width % layer['stride'] == 0):
                    pad_along_width = max(layer['y_filt'] - layer['stride'], 0)
                else:
                    pad_along_width = max(layer['y_filt'] - (in_width % layer['stride']), 0)
                layer['pad_left']  = pad_along_width // 2
                layer['pad_right']  = pad_along_width - layer['pad_left']
            elif layer['padding']=='valid':
                in_width = current_shape[1]
                layer['y_out'] = int(math.ceil(float(in_width - layer['y_filt'] + 1) / float(layer['stride'])))
                layer['pad_left'] = 0
                layer['pad_right'] = 0
            current_shape=[current_shape[0], layer['y_out'], layer['n_filt']]
        print 'Layer name: %s, layer type: %s, current shape: %s, number of zeros: %s'%(layer['name'], layer['class_name'], current_shape, cur_n_zeros)
        layer_list.append( layer )
        

    #################
    ## Generate HLS
    #################

    #Weights and biases are already dumped to output directory
    #Now generate HLS from list of layer dictionaries
    hls_writer(layer_list, yamlConfig)


if __name__ == "__main__":
    main()
