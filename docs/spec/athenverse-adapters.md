# Athenverse adapters

Status: Working doctrine
Scope: Hermes Agent adapters over Interverse capabilities
Canonical ecosystem: Sylveste / Interverse

## Purpose

This note defines the boundary between Interverse and Athenverse.

- Interverse names canonical Sylveste ecosystem skills/plugins.
- Athenverse names Hermes-specialized adapters over those capabilities.

The goal is to preserve provenance while allowing Hermes-native orchestration, synthesis, prompting, and workflow semantics to develop as a distinct layer.

## Core distinction

### Interverse

Use `inter*` names for ecosystem-native capabilities that should exist independently of Hermes.

A capability belongs in Interverse when it is:
- canonical to the Sylveste ecosystem
- usable by clients other than Hermes
- meaningful without Hermes-specific prompting or orchestration
- intended to remain the source capability rather than a host-specific wrapper

Examples:
- `interflux` = canonical review framework / plugin
- `interpath` = canonical path/workflow capability
- `interknow` = canonical knowledge capability

### Athenverse

Use `Athen*` names for Hermes-specialized adapters that materially change how Hermes invokes, interprets, or operationalizes an Interverse capability.

An adapter belongs in Athenverse when it adds one or more of:
- Hermes-specific orchestration
- Hermes-specific synthesis
- Hermes-specific prompting conventions
- Hermes-specific workflow policy
- Hermes-specific runtime UX or operator semantics

A thin pass-through wrapper does not automatically deserve an `Athen*` identity.

## Naming rule

Keep the canonical `inter*` name when the artifact is still the native ecosystem capability.

Use an `Athen*` name only when the Hermes-side layer is substantial enough to have its own:
- behavior contract
- operating assumptions
- user mental model
- documentation surface

Practical threshold:
- if the Hermes layer is mostly a transport shim, keep the canonical name
- if the Hermes layer adds real doctrine and operating semantics, it may become `Athen*`

## First plugin: Athenflux

`Athenflux` is the first Athenverse plugin.

Relationship to `interflux`:
- `interflux` remains the canonical review framework/spec in Interverse
- `Athenflux` is the Hermes-native operational layer over `interflux`
- `Athenflux` may add Hermes-specific review routing, synthesis, prompt structure, artifact status semantics, or operator workflow on top of canonical `interflux` behavior

This means:
- `interflux` is source capability
- `Athenflux` is Hermes-specialized adaptation

## Future examples

These names are illustrative, not automatically approved:
- `Athenpath`
- `Athenknow`
- `Athenmem`

Each should only be adopted if the Hermes-side layer is materially opinionated rather than a thin wrapper.

## Anti-examples

Do not mint an `Athen*` name when:
- Hermes is only forwarding calls unchanged
- the layer has no independent doctrine or operator semantics
- the only distinction is implementation location
- the adapter would confuse provenance more than it clarifies usage

## One-line doctrine

Interverse defines canonical ecosystem capabilities; Athenverse defines Hermes-specialized adapters over those capabilities, with `Athenflux` as the first concrete example.
