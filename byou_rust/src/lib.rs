use pyo3::prelude::*;
use pyo3::types::PyDict;

mod complexity;
mod field_extractor;

/// Byou Rust extension — high-performance modules for the Byou BD Multi-Agent system.
///
/// Install (開発):
///   cd byou_rust && maturin develop --release
///
/// Install (本番):
///   cd byou_rust && maturin build --release
///   pip install target/wheels/byou_rust-*.whl
#[pymodule]
fn _byou_rust(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_class::<complexity::ComplexityClassifierRs>()?;
    m.add_function(wrap_pyfunction!(field_extractor::extract_fields_rs, m)?)?;
    m.add_function(wrap_pyfunction!(field_extractor::extract_fields_from_text_rs, m)?)?;
    Ok(())
}
