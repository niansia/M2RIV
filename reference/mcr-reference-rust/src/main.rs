use anyhow::{Context, Result, anyhow, bail};
use serde::Deserialize;
use serde_json::{Map, Number, Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeSet, HashSet};
use std::env;
use std::fs;
use std::path::Path;

const CONTENT_ID_PREFIX: &str = "m2riv:sha256:";

fn python_float(value: f64) -> Result<String> {
    if !value.is_finite() {
        bail!("identity-bearing floats must be finite");
    }
    if value == 0.0 {
        return Ok(if value.is_sign_negative() {
            "-0.0".to_owned()
        } else {
            "0.0".to_owned()
        });
    }

    let sign = if value.is_sign_negative() { "-" } else { "" };
    let mut buffer = ryu::Buffer::new();
    let raw = buffer.format_finite(value.abs()).to_ascii_lowercase();
    let (coefficient, explicit_exponent) = match raw.split_once('e') {
        Some((coefficient, exponent)) => (
            coefficient,
            exponent
                .parse::<i32>()
                .with_context(|| format!("invalid Ryu exponent: {raw}"))?,
        ),
        None => (raw.as_str(), 0),
    };
    let decimal_position = coefficient.find('.').unwrap_or(coefficient.len());
    let all_digits = coefficient.replace('.', "");
    let first_significant = all_digits
        .bytes()
        .position(|byte| byte != b'0')
        .ok_or_else(|| anyhow!("zero must be handled before decimal normalization"))?;
    let first_exponent = decimal_position as i32 - first_significant as i32 - 1 + explicit_exponent;
    let significant = all_digits[first_significant..].trim_end_matches('0');

    if (-4..16).contains(&first_exponent) {
        if first_exponent < 0 {
            return Ok(format!(
                "{sign}0.{}{significant}",
                "0".repeat((-first_exponent - 1) as usize)
            ));
        }
        let integer_digits = (first_exponent + 1) as usize;
        if significant.len() <= integer_digits {
            return Ok(format!(
                "{sign}{significant}{}.0",
                "0".repeat(integer_digits - significant.len())
            ));
        }
        return Ok(format!(
            "{sign}{}.{}",
            &significant[..integer_digits],
            &significant[integer_digits..]
        ));
    }

    let mantissa = if significant.len() == 1 {
        significant.to_owned()
    } else {
        format!("{}.{}", &significant[..1], &significant[1..])
    };
    let exponent_sign = if first_exponent < 0 { '-' } else { '+' };
    Ok(format!(
        "{sign}{mantissa}e{exponent_sign}{:02}",
        first_exponent.abs()
    ))
}

fn canonical_json(value: &Value) -> Result<String> {
    match value {
        Value::Null => Ok("null".to_owned()),
        Value::Bool(value) => Ok(value.to_string()),
        Value::Number(value) => {
            if let Some(integer) = value.as_i64() {
                Ok(integer.to_string())
            } else if let Some(integer) = value.as_u64() {
                Ok(integer.to_string())
            } else {
                python_float(
                    value
                        .as_f64()
                        .ok_or_else(|| anyhow!("unsupported JSON number"))?,
                )
            }
        }
        Value::String(value) => serde_json::to_string(value).context("serialize JSON string"),
        Value::Array(values) => {
            let encoded = values
                .iter()
                .map(canonical_json)
                .collect::<Result<Vec<_>>>()?;
            Ok(format!("[{}]", encoded.join(",")))
        }
        Value::Object(values) => {
            let mut keys = values.keys().collect::<Vec<_>>();
            keys.sort_by(|left, right| left.chars().cmp(right.chars()));
            let encoded = keys
                .into_iter()
                .map(|key| {
                    Ok(format!(
                        "{}:{}",
                        serde_json::to_string(key).context("serialize object key")?,
                        canonical_json(&values[key])?
                    ))
                })
                .collect::<Result<Vec<_>>>()?;
            Ok(format!("{{{}}}", encoded.join(",")))
        }
    }
}

fn fingerprint(value: &Value, namespace: &str) -> Result<String> {
    if namespace.is_empty() || namespace.contains('\0') {
        bail!("namespace must be non-empty and contain no NUL bytes");
    }
    let canonical = canonical_json(value)?;
    let mut digest = Sha256::new();
    digest.update(format!("m2riv:{namespace}:v1").as_bytes());
    digest.update([0]);
    digest.update(canonical.as_bytes());
    let digest = digest.finalize();
    Ok(format!("{digest:x}"))
}

fn content_id(value: &Value, namespace: &str) -> Result<String> {
    Ok(format!(
        "{CONTENT_ID_PREFIX}{}",
        fingerprint(value, namespace)?
    ))
}

fn normalize_datetime(timestamp: &str) -> Result<String> {
    if !timestamp.contains('T') {
        bail!("typed datetime must contain a date/time separator");
    }
    if let Some(prefix) = timestamp.strip_suffix('Z') {
        return Ok(format!("{prefix}+00:00"));
    }
    let bytes = timestamp.as_bytes();
    if bytes.len() < 6
        || !matches!(bytes[bytes.len() - 6], b'+' | b'-')
        || bytes[bytes.len() - 3] != b':'
    {
        bail!("typed datetime must include a numeric UTC offset");
    }
    Ok(timestamp.to_owned())
}

fn materialize_typed_value(value: &Value) -> Result<Value> {
    match value {
        Value::Array(values) => Ok(Value::Array(
            values
                .iter()
                .map(materialize_typed_value)
                .collect::<Result<Vec<_>>>()?,
        )),
        Value::Object(values) if values.len() == 1 && values.contains_key("$float64") => {
            let bits = values["$float64"]
                .as_str()
                .ok_or_else(|| anyhow!("$float64 must contain a hexadecimal string"))?;
            if bits.len() != 16 {
                bail!("$float64 must contain exactly 16 hexadecimal digits");
            }
            let bits = u64::from_str_radix(bits, 16).context("parse $float64 bits")?;
            let value = f64::from_bits(bits);
            if !value.is_finite() {
                bail!("$float64 must be finite");
            }
            Ok(Value::Number(
                Number::from_f64(value).ok_or_else(|| anyhow!("invalid finite float"))?,
            ))
        }
        Value::Object(values) if values.len() == 1 && values.contains_key("$integer") => {
            let integer = values["$integer"]
                .as_str()
                .ok_or_else(|| anyhow!("$integer must contain a base-10 string"))?;
            let number = if integer.starts_with('-') {
                Number::from(integer.parse::<i64>().context("parse signed $integer")?)
            } else {
                Number::from(integer.parse::<u64>().context("parse unsigned $integer")?)
            };
            Ok(Value::Number(number))
        }
        Value::Object(values) if values.len() == 1 && values.contains_key("$datetime") => {
            let timestamp = values["$datetime"]
                .as_str()
                .ok_or_else(|| anyhow!("$datetime must contain a string"))?;
            Ok(Value::String(normalize_datetime(timestamp)?))
        }
        Value::Object(values) if values.len() == 1 && values.contains_key("$path") => {
            let path = values["$path"]
                .as_str()
                .ok_or_else(|| anyhow!("$path must contain a string"))?;
            Ok(Value::String(path.replace('\\', "/")))
        }
        Value::Object(values) if values.len() == 1 && values.contains_key("$set") => {
            let members = values["$set"]
                .as_array()
                .ok_or_else(|| anyhow!("$set must contain an array"))?;
            let mut ordered = BTreeSet::new();
            for member in members {
                ordered.insert(
                    member
                        .as_str()
                        .ok_or_else(|| anyhow!("portable $set members must be strings"))?
                        .to_owned(),
                );
            }
            Ok(Value::Array(
                ordered.into_iter().map(Value::String).collect(),
            ))
        }
        Value::Object(values) => Ok(Value::Object(
            values
                .iter()
                .map(|(key, value)| Ok((key.clone(), materialize_typed_value(value)?)))
                .collect::<Result<Map<_, _>>>()?,
        )),
        _ => Ok(value.clone()),
    }
}

#[derive(Deserialize)]
struct IdentityDocument {
    vectors: Vec<IdentityVector>,
}

#[derive(Deserialize)]
struct IdentityVector {
    name: String,
    namespace: String,
    value: Option<Value>,
    typed_value: Option<Value>,
    canonical_json: String,
    sha256: String,
}

fn verify_vectors(path: &Path) -> Result<()> {
    let document: IdentityDocument = serde_json::from_slice(
        &fs::read(path).with_context(|| format!("read vectors from {}", path.display()))?,
    )
    .context("parse identity vectors")?;
    for vector in &document.vectors {
        let source = match (&vector.value, &vector.typed_value) {
            (Some(value), None) | (None, Some(value)) => value,
            _ => bail!("vector {} must define exactly one value", vector.name),
        };
        let value = materialize_typed_value(source)?;
        let canonical = canonical_json(&value)?;
        if canonical != vector.canonical_json {
            bail!(
                "canonical JSON mismatch for {}\nexpected: {}\nactual:   {}",
                vector.name,
                vector.canonical_json,
                canonical
            );
        }
        let digest = fingerprint(&value, &vector.namespace)?;
        if digest != vector.sha256 {
            bail!("fingerprint mismatch for {}", vector.name);
        }
    }
    println!(
        "verified {} M2RIV v1 identity vectors in Rust",
        document.vectors.len()
    );
    Ok(())
}

#[derive(Deserialize)]
struct FloatDocument {
    vectors: Vec<FloatVector>,
}

#[derive(Deserialize)]
struct FloatVector {
    bits: String,
    canonical_json: String,
    sha256: String,
}

fn verify_float_vectors(path: &Path) -> Result<()> {
    let document: FloatDocument = serde_json::from_slice(
        &fs::read(path).with_context(|| format!("read float vectors from {}", path.display()))?,
    )
    .context("parse float vectors")?;
    for vector in &document.vectors {
        if vector.bits.len() != 16 {
            bail!("float vector bits must contain 16 hexadecimal digits");
        }
        let bits = u64::from_str_radix(&vector.bits, 16).context("parse float vector bits")?;
        let value = f64::from_bits(bits);
        if !value.is_finite() {
            bail!("float corpus must contain only finite binary64 values");
        }
        let payload = json!({"value": value});
        let canonical = canonical_json(&payload)?;
        if canonical != vector.canonical_json {
            bail!(
                "float canonical JSON mismatch for {}\nexpected: {}\nactual:   {}",
                vector.bits,
                vector.canonical_json,
                canonical
            );
        }
        if fingerprint(&payload, "float-spelling-corpus")? != vector.sha256 {
            bail!("float fingerprint mismatch for {}", vector.bits);
        }
    }
    println!(
        "verified {} binary64 spelling vectors in Rust",
        document.vectors.len()
    );
    Ok(())
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SimpleEvidence {
    schema_version: String,
    created_at: String,
    baseline_label: String,
    candidate_label: String,
    metric: SimpleMetric,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SimpleMetric {
    metric_id: String,
    unit: String,
    direction: String,
    baseline_value: f64,
    candidate_value: f64,
    non_inferiority_margin: f64,
    sample_size: u64,
}

fn build_report(evidence: &SimpleEvidence) -> Result<Value> {
    if evidence.schema_version != "1.0.0" {
        bail!("simple evidence schema_version must be 1.0.0");
    }
    if !matches!(
        evidence.metric.direction.as_str(),
        "higher_is_better" | "lower_is_better"
    ) {
        bail!("simple evidence direction must be higher_is_better or lower_is_better");
    }
    for value in [
        evidence.metric.baseline_value,
        evidence.metric.candidate_value,
        evidence.metric.non_inferiority_margin,
    ] {
        if !value.is_finite() {
            bail!("simple evidence numbers must be finite");
        }
    }
    if evidence.metric.non_inferiority_margin < 0.0 {
        bail!("non_inferiority_margin must be non-negative");
    }

    let created_at = normalize_datetime(&evidence.created_at)?;
    let baseline_id = content_id(
        &Value::String(evidence.baseline_label.clone()),
        "reference-snapshot",
    )?;
    let candidate_id = content_id(
        &Value::String(evidence.candidate_label.clone()),
        "reference-snapshot",
    )?;
    let delta = evidence.metric.candidate_value - evidence.metric.baseline_value;
    let passes = if evidence.metric.direction == "higher_is_better" {
        delta >= -evidence.metric.non_inferiority_margin
    } else {
        delta <= evidence.metric.non_inferiority_margin
    };
    let status = if passes { "PASS" } else { "BLOCK" };
    let metric = json!({
        "metric_id": evidence.metric.metric_id,
        "scope": "overall",
        "unit": evidence.metric.unit,
        "direction": evidence.metric.direction,
        "baseline_value": evidence.metric.baseline_value,
        "candidate_value": evidence.metric.candidate_value,
        "delta": delta,
        "confidence_level": null,
        "interval_lower": null,
        "interval_upper": null,
        "effect_size": null,
        "sample_size": evidence.metric.sample_size,
        "evidence_set_id": null,
        "identity_scope": "evidence"
    });
    let findings = if passes {
        Vec::new()
    } else {
        vec![json!({
            "rule_id": "simple-non-inferiority",
            "status": "BLOCK",
            "message": "candidate exceeds the declared non-inferiority margin",
            "metric_id": evidence.metric.metric_id,
            "evidence": [],
            "evidence_set_id": null
        })]
    };
    let decision = json!({"status": status, "allowed": passes, "findings": findings});
    let finding_evidence = decision["findings"]
        .as_array()
        .context("decision findings must be an array")?
        .iter()
        .map(|finding| {
            json!({
                "rule_id": finding["rule_id"],
                "metric_id": finding["metric_id"],
                "evidence_set_id": finding["evidence_set_id"],
                "evidence": finding["evidence"]
            })
        })
        .collect::<Vec<_>>();
    let evidence_payload = json!({
        "schema_version": "1.3.0",
        "baseline_snapshot_id": baseline_id,
        "candidate_snapshot_id": candidate_id,
        "release_plan_id": null,
        "metrics": [metric.clone()],
        "finding_evidence": finding_evidence,
        "evidence_manifest": null,
        "evidence": []
    });
    let report_id = content_id(&evidence_payload, "model-change-evidence")?;
    let run_payload = json!({
        "schema_version": "1.3.0",
        "evidence_id": report_id,
        "created_at": created_at,
        "baseline_snapshot_id": baseline_id,
        "candidate_snapshot_id": candidate_id,
        "release_plan_id": null,
        "executions": [],
        "metrics": [metric.clone()],
        "decision": decision,
        "evidence_manifest": null,
        "evidence": [],
        "limitations": ["Rust reference conformance evidence; no model was executed."]
    });
    let run_id = content_id(&run_payload, "model-change-run")?;
    Ok(json!({
        "schema_version": "1.3.0",
        "id": report_id,
        "run_id": run_id,
        "created_at": created_at,
        "baseline_snapshot_id": baseline_id,
        "candidate_snapshot_id": candidate_id,
        "release_plan_id": null,
        "executions": [],
        "metrics": [metric],
        "decision": decision,
        "evidence_manifest": null,
        "evidence": [],
        "limitations": ["Rust reference conformance evidence; no model was executed."]
    }))
}

fn produce(input: &Path, output: &Path) -> Result<()> {
    let evidence: SimpleEvidence = serde_json::from_slice(
        &fs::read(input).with_context(|| format!("read evidence from {}", input.display()))?,
    )
    .context("parse simple evidence")?;
    let report = build_report(&evidence)?;
    fs::create_dir_all(output)
        .with_context(|| format!("create output directory {}", output.display()))?;
    let destination = output.join("m2riv-report.json");
    let mut encoded = serde_json::to_string_pretty(&report).context("render MCR report")?;
    encoded.push('\n');
    fs::write(&destination, encoded).with_context(|| format!("write {}", destination.display()))?;
    println!("produced {}", destination.display());
    Ok(())
}

fn object(value: &Value) -> Result<&Map<String, Value>> {
    value
        .as_object()
        .ok_or_else(|| anyhow!("expected a JSON object"))
}

fn required<'a>(value: &'a Map<String, Value>, key: &str) -> Result<&'a Value> {
    value
        .get(key)
        .ok_or_else(|| anyhow!("report is missing required field: {key}"))
}

fn normalize_float_fields(metric: &mut Map<String, Value>) -> Result<()> {
    for key in [
        "baseline_value",
        "candidate_value",
        "delta",
        "confidence_level",
        "interval_lower",
        "interval_upper",
        "effect_size",
    ] {
        let Some(value) = metric.get_mut(key) else {
            continue;
        };
        if value.is_null() {
            continue;
        }
        let number = value
            .as_f64()
            .ok_or_else(|| anyhow!("metric {key} must be numeric or null"))?;
        *value = Value::Number(
            Number::from_f64(number).ok_or_else(|| anyhow!("metric {key} must be finite"))?,
        );
    }
    Ok(())
}

fn normalize_metric(value: &Value) -> Result<Value> {
    let mut metric = object(value)?.clone();
    for (key, default) in [
        ("scope", json!("overall")),
        ("unit", json!("score")),
        ("direction", json!("higher_is_better")),
        ("confidence_level", Value::Null),
        ("interval_lower", Value::Null),
        ("interval_upper", Value::Null),
        ("effect_size", Value::Null),
        ("evidence_set_id", Value::Null),
        ("identity_scope", json!("evidence")),
    ] {
        metric.entry(key.to_owned()).or_insert(default);
    }
    normalize_float_fields(&mut metric)?;
    Ok(Value::Object(metric))
}

fn normalize_finding(value: &Value) -> Result<Value> {
    let mut finding = object(value)?.clone();
    for (key, default) in [
        ("metric_id", Value::Null),
        ("evidence", json!([])),
        ("evidence_set_id", Value::Null),
    ] {
        finding.entry(key.to_owned()).or_insert(default);
    }
    Ok(Value::Object(finding))
}

fn normalize_decision(value: &Value) -> Result<Value> {
    let mut decision = object(value)?.clone();
    let findings = decision.entry("findings").or_insert_with(|| json!([]));
    let normalized = findings
        .as_array()
        .ok_or_else(|| anyhow!("decision findings must be an array"))?
        .iter()
        .map(normalize_finding)
        .collect::<Result<Vec<_>>>()?;
    *findings = Value::Array(normalized);
    Ok(Value::Object(decision))
}

fn normalize_executions(value: &Value) -> Result<Value> {
    let executions = value
        .as_array()
        .ok_or_else(|| anyhow!("executions must be an array"))?;
    Ok(Value::Array(
        executions
            .iter()
            .map(|execution| {
                let mut execution = object(execution)?.clone();
                execution.entry("runtime_profile").or_insert(Value::Null);
                execution.entry("capabilities").or_insert_with(|| json!([]));
                execution.entry("cache_hits").or_insert_with(|| json!(0));
                let capabilities = execution["capabilities"]
                    .as_array()
                    .ok_or_else(|| anyhow!("execution capabilities must be an array"))?;
                let ordered = capabilities
                    .iter()
                    .map(|item| {
                        item.as_str()
                            .map(str::to_owned)
                            .ok_or_else(|| anyhow!("execution capability must be a string"))
                    })
                    .collect::<Result<BTreeSet<_>>>()?;
                execution.insert(
                    "capabilities".to_owned(),
                    Value::Array(ordered.into_iter().map(Value::String).collect()),
                );
                Ok(Value::Object(execution))
            })
            .collect::<Result<Vec<_>>>()?,
    ))
}

fn verify_report(source: &Path) -> Result<()> {
    let report_path = if source.is_dir() {
        source.join("m2riv-report.json")
    } else {
        source.to_owned()
    };
    let report: Value = serde_json::from_slice(
        &fs::read(&report_path)
            .with_context(|| format!("read MCR report from {}", report_path.display()))?,
    )
    .context("parse MCR report")?;
    let report = object(&report)?;
    if required(report, "schema_version")? != "1.3.0" {
        bail!("Rust reference verifier supports MCR 1.3.0");
    }

    let metrics = report
        .get("metrics")
        .unwrap_or(&json!([]))
        .as_array()
        .ok_or_else(|| anyhow!("metrics must be an array"))?
        .iter()
        .map(normalize_metric)
        .collect::<Result<Vec<_>>>()?;
    let stable_metrics = metrics
        .iter()
        .filter(|metric| metric["identity_scope"] == "evidence")
        .cloned()
        .collect::<Vec<_>>();
    let stable_metric_ids = stable_metrics
        .iter()
        .filter_map(|metric| metric["metric_id"].as_str().map(str::to_owned))
        .collect::<HashSet<_>>();
    let decision = normalize_decision(required(report, "decision")?)?;
    let decision_object = object(&decision)?;
    let findings = decision_object["findings"]
        .as_array()
        .context("decision findings must be an array")?;
    let finding_evidence = findings
        .iter()
        .filter(|finding| {
            finding["metric_id"].is_null()
                || finding["metric_id"]
                    .as_str()
                    .is_some_and(|metric_id| stable_metric_ids.contains(metric_id))
        })
        .map(|finding| {
            json!({
                "rule_id": finding["rule_id"],
                "metric_id": finding["metric_id"],
                "evidence_set_id": finding["evidence_set_id"],
                "evidence": finding["evidence"]
            })
        })
        .collect::<Vec<_>>();
    let release_plan_id = report
        .get("release_plan_id")
        .cloned()
        .unwrap_or(Value::Null);
    let evidence_manifest = report
        .get("evidence_manifest")
        .cloned()
        .unwrap_or(Value::Null);
    let evidence = report.get("evidence").cloned().unwrap_or_else(|| json!([]));
    let evidence_payload = json!({
        "schema_version": "1.3.0",
        "baseline_snapshot_id": required(report, "baseline_snapshot_id")?,
        "candidate_snapshot_id": required(report, "candidate_snapshot_id")?,
        "release_plan_id": release_plan_id,
        "metrics": stable_metrics,
        "finding_evidence": finding_evidence,
        "evidence_manifest": evidence_manifest,
        "evidence": evidence
    });
    let expected_report_id = content_id(&evidence_payload, "model-change-evidence")?;
    if required(report, "id")? != &expected_report_id {
        bail!("MCR evidence identity does not match its contents");
    }

    let created_at = required(report, "created_at")?
        .as_str()
        .ok_or_else(|| anyhow!("created_at must be a string"))?;
    let executions = normalize_executions(report.get("executions").unwrap_or(&json!([])))?;
    let run_payload = json!({
        "schema_version": "1.3.0",
        "evidence_id": expected_report_id,
        "created_at": normalize_datetime(created_at)?,
        "baseline_snapshot_id": required(report, "baseline_snapshot_id")?,
        "candidate_snapshot_id": required(report, "candidate_snapshot_id")?,
        "release_plan_id": release_plan_id,
        "executions": executions,
        "metrics": metrics,
        "decision": decision,
        "evidence_manifest": evidence_manifest,
        "evidence": evidence,
        "limitations": report.get("limitations").cloned().unwrap_or_else(|| json!([]))
    });
    let expected_run_id = content_id(&run_payload, "model-change-run")?;
    if required(report, "run_id")? != &expected_run_id {
        bail!("MCR run identity does not match its contents");
    }

    let status = decision_object["status"]
        .as_str()
        .ok_or_else(|| anyhow!("decision status must be a string"))?;
    let allowed = decision_object["allowed"]
        .as_bool()
        .ok_or_else(|| anyhow!("decision allowed must be boolean"))?;
    if (status == "PASS" && !allowed) || (matches!(status, "BLOCK" | "ERROR") && allowed) {
        bail!("decision status and allowed flag disagree");
    }
    println!(
        "verified MCR 1.3 report in Rust: {} {}",
        status, expected_report_id
    );
    Ok(())
}

fn usage(program: &str) -> String {
    format!(
        "usage:\n  {program} vectors GOLDEN-VECTORS.json\n  {program} float-vectors FLOAT-VECTORS.json\n  {program} produce SIMPLE-EVIDENCE.json OUTPUT-DIR\n  {program} verify BUNDLE-OR-REPORT"
    )
}

fn run() -> Result<()> {
    let arguments = env::args().collect::<Vec<_>>();
    let program = arguments
        .first()
        .map(String::as_str)
        .unwrap_or("mcr-reference-rust");
    match arguments.as_slice() {
        [_, command, path] if command == "vectors" => verify_vectors(Path::new(path)),
        [_, command, path] if command == "float-vectors" => verify_float_vectors(Path::new(path)),
        [_, command, input, output] if command == "produce" => {
            produce(Path::new(input), Path::new(output))
        }
        [_, command, source] if command == "verify" => verify_report(Path::new(source)),
        _ => bail!(usage(program)),
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("ERROR: {error:#}");
        std::process::exit(2);
    }
}

#[cfg(test)]
mod tests {
    use super::python_float;

    #[test]
    fn formats_python_float_boundaries() {
        let cases = [
            (-0.0, "-0.0"),
            (1.0, "1.0"),
            (1e-5, "1e-05"),
            (1e-4, "0.0001"),
            (1e15, "1000000000000000.0"),
            (1e16, "1e+16"),
            (f64::from_bits(1), "5e-324"),
            (f64::MIN_POSITIVE, "2.2250738585072014e-308"),
            (f64::MAX, "1.7976931348623157e+308"),
            (0.30000000000000004, "0.30000000000000004"),
        ];
        for (value, expected) in cases {
            assert_eq!(python_float(value).unwrap(), expected);
        }
    }
}
