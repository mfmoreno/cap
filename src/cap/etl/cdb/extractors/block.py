from typing import Any, Optional, Iterator
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from opentelemetry import trace
import logging

from cap.etl.cdb.extractors.extractor import BaseExtractor
from cap.data.cdb_model import Block, SlotLeader, Tx

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

class BlockExtractor(BaseExtractor):
    """Extracts block data from cardano-db-sync."""

    def extract_batch(self, last_processed_id: Optional[int] = None) -> Iterator[list[dict[str, Any]]]:
        """Extract blocks in batches."""
        with tracer.start_as_current_span("block_extraction") as span:
            query = self.db_session.query(Block).options(
                joinedload(Block.slot_leader).joinedload(SlotLeader.pool_hash)
            )

            if last_processed_id:
                query = query.filter(Block.id > last_processed_id)

            query = query.order_by(Block.id)

            offset = 0
            while True:
                batch = query.offset(offset).limit(self.batch_size).all()
                if not batch:
                    break

                span.set_attribute("batch_size", len(batch))
                span.set_attribute("offset", offset)

                yield [self._serialize_block(block) for block in batch]
                offset += self.batch_size

    def _serialize_block(self, block: Block) -> dict[str, Any]:
        """Serialize a block to dictionary."""

        transactions = self.db_session.query(Tx).filter(
            Tx.block_id == block.id
        ).all()

        return {
            'id': block.id,
            'hash': block.hash.hex() if block.hash else None,
            'epoch_no': block.epoch_no,
            'slot_no': block.slot_no,
            'epoch_slot_no': block.epoch_slot_no,
            'block_no': block.block_no,
            'previous_id': block.previous_id,
            'slot_leader_id': block.slot_leader_id,
            'slot_leader_hash': block.slot_leader.hash.hex() if block.slot_leader and block.slot_leader.hash else None,
            'pool_hash': block.slot_leader.pool_hash.view if block.slot_leader and block.slot_leader.pool_hash else None,
            'size': block.size,
            'time': block.time.isoformat() if block.time else None,
            'tx_count': block.tx_count,
            'proto_major': block.proto_major,
            'proto_minor': block.proto_minor,
            'vrf_key': block.vrf_key,
            'op_cert_counter': block.op_cert_counter,
            'transactions': [{'hash': tx.hash.hex(), 'epoch_no': block.epoch_no} for tx in transactions]
        }

    def get_total_count(self) -> int:
        return self.db_session.query(func.count(Block.id)).scalar()

    def get_last_id(self) -> Optional[int]:
        result = self.db_session.query(func.max(Block.id)).scalar()
        return result