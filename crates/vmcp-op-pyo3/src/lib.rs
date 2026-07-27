//! Thin PyO3 façade for the pure vmcp-operator core.

use pyo3::prelude::*;

/// Exercise the free-threaded boundary with owned data and detached Rust work.
#[pyfunction]
fn sha256_hex(py: Python<'_>, value: Vec<u8>) -> String {
    py.detach(move || vmcp_op_core::sha256_hex(&value))
}

/// Python extension module. The core contains no Python references or mutable
/// process-global state, so this module is safe to import without the GIL.
#[pymodule(gil_used = false)]
fn _kernel(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(sha256_hex, module)?)?;
    Ok(())
}
