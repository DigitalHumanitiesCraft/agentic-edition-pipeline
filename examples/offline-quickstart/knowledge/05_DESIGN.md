---
title: Offline Quickstart Design
description: Minimal frontend requirements for the synthetic offline example
tags: [design, example]
---

# Offline Quickstart Design

## Usage goal

An evaluator can browse the two synthetic documents, search their catalog metadata, read their page text, and inspect the generated TEI.

## Components

The example uses the standard catalog, search, document view, TEI download, and plaintext export. A facsimile viewer is present in the shared frontend, though the synthetic corpus contains no images.

## Verification scope

The automated run verifies generated files, catalog completeness, XML well-formedness, and RelaxNG conformance. Editorial quality and user acceptance remain outside this automated example.
