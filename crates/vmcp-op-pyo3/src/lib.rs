//! Thin PyO3 façade for the pure vmcp-operator core.

use std::collections::BTreeMap;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use vmcp_op_core::{
    DesiredHttpUpstream, DesiredSkill, DesiredSkillArg, DesiredUpstreamArtifacts, TaskSupport,
    ToolOverride, image_allowed as core_image_allowed,
    render_artifact_bundle as core_render_artifact_bundle, render_registry as core_render_registry,
    sha256_hex as core_sha256_hex,
};

fn map_err(err: vmcp_op_core::CoreError) -> PyErr {
    PyValueError::new_err(err.to_string())
}

/// Exercise the free-threaded boundary with owned data and detached Rust work.
#[pyfunction]
fn sha256_hex(py: Python<'_>, value: Vec<u8>) -> String {
    py.detach(move || core_sha256_hex(&value))
}

#[derive(FromPyObject)]
struct PyDesiredHttpUpstream {
    name: String,
    url: String,
    bearer_env: Option<String>,
    description: Option<String>,
    sidecar_relpath: Option<String>,
    enabled: bool,
}

impl From<PyDesiredHttpUpstream> for DesiredHttpUpstream {
    fn from(value: PyDesiredHttpUpstream) -> Self {
        Self {
            name: value.name,
            url: value.url,
            bearer_env: value.bearer_env,
            description: value.description,
            sidecar_relpath: value.sidecar_relpath,
            enabled: value.enabled,
        }
    }
}

#[derive(FromPyObject)]
struct PyToolOverride {
    name: String,
    read_only: bool,
    task_support: Option<String>,
}

fn parse_task_support(raw: Option<String>) -> PyResult<Option<TaskSupport>> {
    match raw.as_deref() {
        None => Ok(None),
        Some("forbidden") => Ok(Some(TaskSupport::Forbidden)),
        Some("optional") => Ok(Some(TaskSupport::Optional)),
        Some("required") => Ok(Some(TaskSupport::Required)),
        Some(other) => Err(PyValueError::new_err(format!(
            "invalid taskSupport `{other}`"
        ))),
    }
}

#[pyclass]
struct RenderOut {
    #[pyo3(get)]
    text: String,
    #[pyo3(get)]
    sha256: String,
}

#[pyfunction]
fn render_registry(py: Python<'_>, upstreams: Vec<PyDesiredHttpUpstream>) -> PyResult<RenderOut> {
    let owned: Vec<DesiredHttpUpstream> = upstreams.into_iter().map(Into::into).collect();
    let rendered = py.detach(move || core_render_registry(owned).map_err(map_err))?;
    Ok(RenderOut {
        text: rendered.text,
        sha256: rendered.sha256,
    })
}

#[derive(FromPyObject)]
struct PyDesiredSkillArg {
    name: String,
    description: Option<String>,
    required: bool,
    default: Option<String>,
}

#[derive(FromPyObject)]
struct PyDesiredSkill {
    name: String,
    description: String,
    arguments: Vec<PyDesiredSkillArg>,
    template: String,
}

#[derive(FromPyObject)]
struct PyDesiredUpstreamArtifacts {
    upstream: PyDesiredHttpUpstream,
    tool_overrides: Vec<PyToolOverride>,
}

#[pyclass]
struct ArtifactFileOut {
    #[pyo3(get)]
    path: String,
    #[pyo3(get)]
    data: String,
    #[pyo3(get)]
    sha256: String,
}

#[pyclass]
struct ArtifactBundleOut {
    #[pyo3(get)]
    files: BTreeMap<String, Py<ArtifactFileOut>>,
    #[pyo3(get)]
    registry_sha256: String,
    #[pyo3(get)]
    bundle_sha256: String,
    #[pyo3(get)]
    total_bytes: usize,
}

#[pyfunction]
fn render_artifact_bundle(
    py: Python<'_>,
    upstreams: Vec<PyDesiredUpstreamArtifacts>,
    skills: Vec<PyDesiredSkill>,
) -> PyResult<ArtifactBundleOut> {
    let mut desired = Vec::with_capacity(upstreams.len());
    for item in upstreams {
        let mut overrides = Vec::with_capacity(item.tool_overrides.len());
        for ov in item.tool_overrides {
            overrides.push(ToolOverride {
                name: ov.name,
                read_only: ov.read_only,
                task_support: parse_task_support(ov.task_support)?,
            });
        }
        desired.push(DesiredUpstreamArtifacts {
            upstream: item.upstream.into(),
            tool_overrides: overrides,
        });
    }
    let desired_skills = skills
        .into_iter()
        .map(|s| DesiredSkill {
            name: s.name,
            description: s.description,
            arguments: s
                .arguments
                .into_iter()
                .map(|a| DesiredSkillArg {
                    name: a.name,
                    description: a.description,
                    required: a.required,
                    default: a.default,
                })
                .collect(),
            template: s.template,
        })
        .collect::<Vec<_>>();

    let bundle =
        py.detach(move || core_render_artifact_bundle(desired, desired_skills).map_err(map_err))?;

    let mut files = BTreeMap::new();
    for (path, file) in bundle.files {
        files.insert(
            path,
            Py::new(
                py,
                ArtifactFileOut {
                    path: file.path,
                    data: file.data,
                    sha256: file.sha256,
                },
            )?,
        );
    }
    Ok(ArtifactBundleOut {
        files,
        registry_sha256: bundle.registry_sha256,
        bundle_sha256: bundle.bundle_sha256,
        total_bytes: bundle.total_bytes,
    })
}

#[pyfunction]
fn image_allowed(py: Python<'_>, image: String, prefixes: Vec<String>) -> PyResult<()> {
    py.detach(move || core_image_allowed(&image, &prefixes).map_err(map_err))
}

/// Python extension module. The core contains no Python references or mutable
/// process-global state, so this module is safe to import without the GIL.
#[pymodule(gil_used = false)]
fn _kernel(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(sha256_hex, module)?)?;
    module.add_function(wrap_pyfunction!(render_registry, module)?)?;
    module.add_function(wrap_pyfunction!(render_artifact_bundle, module)?)?;
    module.add_function(wrap_pyfunction!(image_allowed, module)?)?;
    module.add_class::<RenderOut>()?;
    module.add_class::<ArtifactFileOut>()?;
    module.add_class::<ArtifactBundleOut>()?;
    Ok(())
}
