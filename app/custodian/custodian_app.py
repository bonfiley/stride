# This script contains daemon to be run at Custodian's premises that responds
# to User requests and calls appropriate contract methods for forward 
# transaction (SBTC-->EBTC). The User requests are read from a RabbitMQ 
# messaging Q. The Flask Web microframework is used to receive User requests
# and pass it on to RabbitMQ queue.  This setup is for testing purposes only. 
# For production deployments, a full fledged server like Apache may be 
# considered. 
#
# Author: Bon Filey (bonfiley@gmail.com)
# Copyright 2018 Bromley Labs Inc.

import json
from pymongo import MongoClient
import datetime
from common import config
from common.utils import *
import threading
import copy

class App:
    def __init__(self, log_file, q_name):
        self.event_q = RabbitMQ(q_name)
        self.event_q.channel.basic_consume(self.callback, queue=q_name,
                                           no_ack=True)
        self.logger = init_logger('CUST',  log_file)
        self.db_client = MongoClient() # Default location 
        self.db = self.db_client['custodian-db']
        self.collection = self.db['transactions'] 
        self.w3_rsk = W3Utils(config.rsk, self.logger)
        self.w3_eth = W3Utils(config.eth, self.logger)
        self.eth_contract, self.eth_concise = self.w3_eth.init_contract('StrideEthContract', config.eth.contract_addr) 
        self.rsk_contract, self.rsk_concise = self.w3_rsk.init_contract('StrideRSKContract', config.rsk.contract_addr) 
        # For convenience:
        self.eth_tx = {'from' : config.eth.custodian, 'gas' : config.eth.gas, 
                       'gasPrice' : config.eth.gas_price, 'value' : 0} 
        self.rsk_tx = {'from' : config.rsk.custodian, 'gas' : config.rsk.gas, 
                       'gasPrice' : config.rsk.gas_price, 'value' : 0} 
        
    def start(self):
        self.logger.info('Listening to events ..')
        self.event_q.channel.start_consuming()

    def callback(self, ch, method, properties, body):
        msg = str(body, 'utf-8') # body type is bytes (for some reason)
        self.logger.info('Received: %s' % msg)   
        msg = json.loads(msg)
        if msg['method'] == 'init_sbtc2ebtc':
            func = self.run_fwd_txn
        th = threading.Thread(target = func, args=(msg,)) 
        th.daemon = True
        th.start()
        self.logger.info('%s thread forked' % func)

    def insert_in_db(self, msg):
        # Convert long int to str for db write 
        m = copy.deepcopy(msg) 
        m['id'] = str(m['id'])
        if 'sbtc_amount' in m['params']:
            m['params']['sbtc_amount'] = str(m['params']['sbtc_amount'])
        if 'ebtc_amount' in m['params']:
            m['params']['ebtc_amount'] = str(m['params']['ebtc_amount'])
        self.collection.insert_one(m)
        self.logger.info('msg saved in DB')

    def run_fwd_txn(self, msg): # sbtc->ebtc
        # msg is {}
        self.logger.info('Initiating forward transaction')
        self.insert_in_db(msg)

        txn_id = msg['id']
        pwd_hash = msg['pwd_hash']  # Hex string '0x..'
        pwd_str = msg['pwd_str']
        user_eth = msg['params']['user'] 
        ebtc_amount = msg['params']['sbtc_amount']
        timeout_interval = 100 # Arbitrary
        eth_amount = int(config.eth_ebtc_ratio * ebtc_amount)

        self.logger.info('Depositing Ether to contract..')
        self.eth_tx['value'] = eth_amount # Payable method
        tx_hash = self.eth_concise.fwd_deposit(txn_id, user_eth, 
                     self.w3_eth.w3.toBytes(hexstr = pwd_hash), 
                     timeout_interval, ebtc_amount, transact = self.eth_tx) 
        self.eth_tx['value'] = 0 # Reset 
        status = self.w3_eth.wait_to_be_mined(tx_hash) 
        if status == 'error':
            return 1

        # Wait for user to deposit SBTC on RSK 
        self.logger.info('Waiting for user to deposit SBTC on RSK')  
        event_filter = self.rsk_contract.events.FwdUserDeposited.createFilter(fromBlock = 'latest')
        event = self.w3_rsk.wait_for_event(event_filter, None,
                                           {'txn_id' : txn_id}, 
                                           timeout_interval)
        if event is None:  # Timeout. 
            self.logger.info('Challenge ..')
            tx_hash = self.eth_concise.fwd_no_user_action_challenge(txn_id,
                                                      transact = self.eth_tx) 
            self.w3_eth.wait_to_be_mined(tx_hash)
            self.logger.info('Fwd transaction completed')
            return 0
         
        # Send pwd str to user
        self.logger.info('Ack to User on RSK') 
        tx_hash = self.rsk_concise.fwd_ack(txn_id, bytes(pwd_str, 'utf-8'), 
                                           transact = self.rsk_tx) 
        self.w3_rsk.wait_to_be_mined(tx_hash)

        self.logger.info('Forward transaction completed') 
        return 0

def main():
    app = App('/tmp/stride.log', 'custodian-q')
    app.start()

if __name__== '__main__':
    main()
