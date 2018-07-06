pragma solidity ^0.4.24;

import "rlp.sol";
import "merkle_proof.sol";

contract EthProof {
    using RLP for RLP.RLPItem;
    using RLP for RLP.Iterator;
    using RLP for bytes;

    mapping (bytes32 => BlockHeader) m_blocks;
    uint public m_highest_block;

    struct BlockHeader {
      bytes32   prev_block_hash; // 0 TODO: This was uint earlier. Why?
      bytes32   state_root;      // 3
      bytes32   txn_root;        // 4
      bytes32   receipt_root;    // 5
    }

    /** Helper function 
        TODO: block_hash was defined as uint instead of bytes32. Why? Change
        back if valid reason.
     */
    function parse_block_header(bytes rlp_header) pure internal 
                               returns (BlockHeader) {
        BlockHeader memory header;
        RLP.Iterator memory it = rlp_header.toRLPItem().iterator();

        uint idx;
        while(it.hasNext()) {
            if (idx == 0) 
                header.prev_block_hash = bytes32(it.next().toUint());
            else if (idx == 3) 
                header.state_root = bytes32(it.next().toUint());
            else if (idx == 4) 
                header.txn_root = bytes32(it.next().toUint());
            else if (idx == 5) 
                header.receipt_root = bytes32(it.next().toUint());
            else 
                it.next();
           idx++;
       }
       return header;
    }

    function get_block_number(bytes rlp_header) pure internal returns (
                              uint block_number) {
        RLP.RLPItem[] memory rlp_h = RLP.toList(RLP.toRLPItem(rlp_header));
        block_number = RLP.toUint(rlp_h[8]);
    }

    /**
      Submit Ethereum block headers.  Assumption here is headers are valid. No
      validy check in this function.
      TODO: Who is authorized to submit?
     */
    function submit_block(bytes32 block_hash, bytes rlp_header) public {
        BlockHeader memory header = parse_block_header(rlp_header);
        uint block_number = get_block_number(rlp_header);
        if (block_number > m_highest_block)  
            m_highest_block = block_number; 
        m_blocks[block_hash] = header;
    }

    function check_receipt_proof(bytes value, bytes32 block_hash, bytes path, 
                                 bytes parent_nodes) public returns (bool) {
        bytes32 receipt_root = m_blocks[block_hash].receipt_root;
        return MerklePatriciaProof.verify(value, path, parent_nodes, 
                                          receipt_root);
   
    }

}
