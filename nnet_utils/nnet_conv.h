//
//    rfnoc-hls-neuralnet: Vivado HLS code for neural-net building blocks
//
//    Copyright (C) 2017 EJ Kreinar
//
//    This program is free software: you can redistribute it and/or modify
//    it under the terms of the GNU General Public License as published by
//    the Free Software Foundation, either version 3 of the License, or
//    (at your option) any later version.
//
//    This program is distributed in the hope that it will be useful,
//    but WITHOUT ANY WARRANTY; without even the implied warranty of
//    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
//    GNU General Public License for more details.
//
//    You should have received a copy of the GNU General Public License
//    along with this program.  If not, see <http://www.gnu.org/licenses/>.
//

#ifndef NNET_CONV_H_
#define NNET_CONV_H_

#include "nnet_common.h"
#include <cstdlib>

namespace nnet {

struct conv_config
{
    // Internal data type definitions                                                                                      
    typedef float bias_t;
    typedef float weight_t;
    typedef float accum_t;

    // Convolutional parameters
    static const unsigned pad_left = 4;
    static const unsigned pad_right = 5;
    static const unsigned y_in = 128;
    static const unsigned n_chan = 9;
    static const unsigned y_filt = 10;
    static const unsigned n_filt = 4;
    static const unsigned stride = 1;
    static const unsigned y_out = 128; 
  
    static const unsigned reuse_factor = 1;
    static const bool store_weights_in_bram = false;
};

template<class data_T, class res_T, typename CONFIG_T>
void conv_1d(
	     data_T    data[CONFIG_T::y_in][CONFIG_T::n_chan],
	     res_T     res[CONFIG_T::y_out][CONFIG_T::n_filt],
	     typename CONFIG_T::weight_t  weights[CONFIG_T::y_filt][CONFIG_T::n_chan][CONFIG_T::n_filt],
	     typename CONFIG_T::bias_t    biases[CONFIG_T::n_filt])
{

    data_T   data_padded[CONFIG_T::pad_left + CONFIG_T::y_in + CONFIG_T::pad_right][CONFIG_T::n_chan];
    typename CONFIG_T::accum_t mult[CONFIG_T::y_out][CONFIG_T::n_filt][CONFIG_T::n_chan][CONFIG_T::y_filt];
    typename CONFIG_T::accum_t acc_prechannel[CONFIG_T::y_out][CONFIG_T::n_filt][CONFIG_T::n_chan];
    typename CONFIG_T::accum_t acc[CONFIG_T::y_out][CONFIG_T::n_filt];

    #pragma HLS ARRAY_PARTITION variable=data_padded complete
    #pragma HLS ARRAY_PARTITION variable=mult complete
    #pragma HLS ARRAY_PARTITION variable=acc complete
    #pragma HLS ARRAY_PARTITION variable=acc_prechannel complete
    
    // Use a function_instantiate in case it helps to explicitly optimize unchanging weights/biases 
    #pragma HLS function_instantiate variable=weights,biases
    
    // Parallel mode
    #pragma HLS PIPELINE
    #pragma HLS ARRAY_PARTITION variable=biases complete
  
    // Limit multipliers to control parallelization
    int multiplier_limit = ceil( (CONFIG_T::y_out*CONFIG_T::n_filt*CONFIG_T::n_chan*CONFIG_T::y_filt) / CONFIG_T::reuse_factor ); //TODO: double check, account for zeros
    //#pragma HLS ALLOCATION instances=mul limit=multiplier_limit operation

    
    // Padding
    PadLoop1: for(int ii=0; ii<CONFIG_T::pad_left + CONFIG_T::y_in + CONFIG_T::pad_right; ii++){
        PadLoop2: for(int cc=0; cc<CONFIG_T::n_chan; cc++){
	    if(ii<CONFIG_T::pad_left || ii>=CONFIG_T::pad_left + CONFIG_T::y_in){
	        data_padded[ii][cc] = 0;
	    }
	    else{
	        data_padded[ii][cc] = data[ii-CONFIG_T::pad_left][cc];
 	    }
        } 
    }
    
    
    // Convolve, saving all multiplication results to accumulate later
    ConvOut: for(int ii = 0; ii < CONFIG_T::y_out; ii++) {
        ConvFilt: for(int ff = 0; ff < CONFIG_T::n_filt; ff++){

            ConvChan: for(int cc = 0; cc < CONFIG_T::n_chan; cc++){
		
		//Multiply
                ConvMult: for(int jj = 0; jj < CONFIG_T::y_filt; jj++){
                    mult[ii][ff][cc][jj] = data_padded[ii*CONFIG_T::stride+jj][cc] * weights[jj][cc][ff];
		}

	    }//end channel loop
	}//end filter loop
    }//end output loop


    // Initialize accumulator 
    for(int ii = 0; ii < CONFIG_T::y_out; ii++) {
	for(int ff = 0; ff < CONFIG_T::n_filt; ff++) {
            for(int cc = 0; cc < CONFIG_T::n_chan; cc++){
	        acc_prechannel[ii][ff][cc] = 0;
            }
	}
    }

    
    // Accumulate multiplication result, leaving channels unsummed for now
    AccumOutPreChan: for(int ii = 0; ii < CONFIG_T::y_out; ii++) {
        AccumFiltPreChan: for(int ff = 0; ff < CONFIG_T::n_filt; ff++) {
            AccumChanPreChan: for(int cc = 0; cc < CONFIG_T::n_chan; cc++){
                AccumDotPreChan: for(int jj = 0; jj < CONFIG_T::y_filt; jj++){
		    acc_prechannel[ii][ff][cc] += mult[ii][ff][cc][jj];
                }//end dot product loop
	    }//end channel loop
	}//end filter loop
    }//end output loop


    // Initialize final accumulator for sum over channels
    for(int ii = 0; ii < CONFIG_T::y_out; ii++) {
	for(int ff = 0; ff < CONFIG_T::n_filt; ff++) {
            acc[ii][ff] = biases[ff];
	}
    }


    // Accumulate multiplication result, with sum over channels
    AccumOut: for(int ii = 0; ii < CONFIG_T::y_out; ii++) {
        AccumFilt: for(int ff = 0; ff < CONFIG_T::n_filt; ff++) {
            AccumChan: for(int cc = 0; cc < CONFIG_T::n_chan; cc++){
		    acc[ii][ff] += acc_prechannel[ii][ff][cc];
	    }//end channel loop
	}//end filter loop
    }//end output loop

    
     // Cast to "res_t" type 
    for(int ii = 0; ii < CONFIG_T::y_out; ii++) {
	for(int ff = 0; ff < CONFIG_T::n_filt; ff++) {
	    res[ii][ff] = (res_T)(acc[ii][ff]);
	}
    }

}

}//end namespace

#endif
