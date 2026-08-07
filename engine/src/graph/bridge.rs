//! Arrow-version IPC bridge between the engine's arrow tree and lance-graph's.

use super::{GraphSpikeError, GraphSpikeErrorKind};

pub(crate) trait DecodeAllBatches {
    type RecordBatch;
    fn decode_all(self) -> Result<Self::RecordBatch, GraphSpikeError>;
}

impl<R: std::io::Read> DecodeAllBatches for arrow_ipc_lg::reader::StreamReader<R> {
    type RecordBatch = arrow_lg::record_batch::RecordBatch;
    fn decode_all(mut self) -> Result<Self::RecordBatch, GraphSpikeError> {
        let schema = self.schema();
        let mut batches = Vec::new();
        while let Some(batch) = self
            .next()
            .transpose()
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("ipc decode: {e}")))?
        {
            batches.push(batch);
        }

        if batches.is_empty() {
            return Err(GraphSpikeError::new(
                GraphSpikeErrorKind::Bridge,
                "empty batch produced by bridge",
            ));
        }

        if batches.len() == 1 {
            return Ok(batches.remove(0));
        }

        arrow_lg::compute::concat_batches(&schema, batches.iter())
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("ipc concat: {e}")))
    }
}

impl<R: std::io::Read> DecodeAllBatches for arrow_ipc::reader::StreamReader<R> {
    type RecordBatch = arrow_array::RecordBatch;
    fn decode_all(mut self) -> Result<Self::RecordBatch, GraphSpikeError> {
        let schema = self.schema();
        let mut batches = Vec::new();
        while let Some(batch) = self
            .next()
            .transpose()
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("ipc decode: {e}")))?
        {
            batches.push(batch);
        }

        if batches.is_empty() {
            return Err(GraphSpikeError::new(
                GraphSpikeErrorKind::Bridge,
                "empty batch produced by bridge",
            ));
        }

        if batches.len() == 1 {
            return Ok(batches.remove(0));
        }

        arrow_select::concat::concat_batches(&schema, batches.iter())
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("ipc concat: {e}")))
    }
}

pub(crate) fn decode_all_batches<T: DecodeAllBatches>(
    reader: T,
) -> Result<T::RecordBatch, GraphSpikeError> {
    reader.decode_all()
}

/// Bridges an engine-native (arrow ~58.3) batch into lance-graph's arrow ^56.2 type.
///
/// Encodes `batch` with this crate's `arrow-ipc` (~58.3) writer and decodes it with
/// the renamed `arrow-ipc-lg` (^56.2) reader — a real IPC round-trip, not a cast,
/// since the two `RecordBatch` types come from structurally distinct arrow-rs majors.
///
/// # Errors
/// Returns a [`GraphSpikeError`] with kind [`GraphSpikeErrorKind::Bridge`] if IPC
/// encoding, decoding, or the source batch fails to produce any decoded batch.
pub(crate) fn bridge_batch(
    batch: &arrow_array::RecordBatch,
) -> Result<arrow_lg::record_batch::RecordBatch, GraphSpikeError> {
    let mut buf = Vec::new();
    {
        let mut writer = arrow_ipc::writer::StreamWriter::try_new(&mut buf, &batch.schema())
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("ipc encode: {e}")))?;
        writer
            .write(batch)
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("ipc encode: {e}")))?;
        writer
            .finish()
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("ipc encode: {e}")))?;
    }
    let reader = arrow_ipc_lg::reader::StreamReader::try_new(buf.as_slice(), None)
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("ipc decode: {e}")))?;
    decode_all_batches(reader)
}

/// Bridges a lance-graph (arrow ^56.2) batch back into the engine's arrow ~58.3 type.
///
/// Inverse of [`bridge_batch`]: encodes with `arrow-ipc-lg` (^56.2) and decodes with
/// this crate's `arrow-ipc` (~58.3), so downstream engine code sees its own arrow type.
///
/// # Errors
/// Returns a [`GraphSpikeError`] with kind [`GraphSpikeErrorKind::Bridge`] if IPC
/// encoding, decoding, or the source batch fails to produce any decoded batch.
pub(crate) fn bridge_batch_back(
    batch: &arrow_lg::record_batch::RecordBatch,
) -> Result<arrow_array::RecordBatch, GraphSpikeError> {
    let mut buf = Vec::new();
    {
        let mut writer = arrow_ipc_lg::writer::StreamWriter::try_new(&mut buf, &batch.schema())
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("ipc encode: {e}")))?;
        writer
            .write(batch)
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("ipc encode: {e}")))?;
        writer
            .finish()
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("ipc encode: {e}")))?;
    }
    let reader = arrow_ipc::reader::StreamReader::try_new(buf.as_slice(), None)
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("ipc decode: {e}")))?;
    decode_all_batches(reader)
}
