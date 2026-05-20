# OSI Salesforce Converter

A two-way converter between [OSI semantic models](../../core-spec/spec.md) and [Salesforce Semantic Model](https://developer.salesforce.com/docs/data/semantic-layer/guide/salesforce-semantic-model-schema.html).

This converter provides lossless, bidirectional conversion between OSI YAML format and Salesforce Semantic Model JSON format.

## Requirements

- **Java 17+**
- **Maven 3.6+** — required to build the jar

## Building

Build the executable jar from source:

```bash
mvn clean package
```

This produces a self-contained executable jar at `target/osi-salesforce-converter-0.1.0-SNAPSHOT.jar` with all dependencies bundled.

## Setup

Both schemas must be obtained and placed under `src/main/resources/schemas/` before building, so they get bundled into the jar.

### Salesforce Semantic Model Schema

1. Visit the [Salesforce Semantic Model Schema documentation](https://developer.salesforce.com/docs/data/semantic-layer/guide/salesforce-semantic-model-schema.html)
2. Copy the JSON schema content from the page
3. Save it to `src/main/resources/schemas/salesforce-semantic-model-schema.json`

### OSI Schema

1. Visit the [OSI schema on GitHub](https://github.com/open-semantic-interchange/OSI/blob/main/core-spec/osi-schema.json)
2. Copy the raw JSON contents
3. Save it to `src/main/resources/schemas/osi-schema.json`

## Usage

### Command Line

#### Import (Salesforce → OSI)

Convert a Salesforce Semantic Model JSON file to OSI YAML format:

```bash
java -jar target/osi-salesforce-converter-0.1.0-SNAPSHOT.jar toOSI input.json
# Output: Customer_Orders_Model.yaml (named after model's 'name' field)
# Created in the same directory as the input file
```

Example:
```bash
java -jar target/osi-salesforce-converter-0.1.0-SNAPSHOT.jar toOSI \
  src/test/resources/examples/salesforceToOsi.json
# Output: src/test/resources/examples/Customer_Orders_Model.yaml
```

#### Export (OSI → Salesforce)

Convert an OSI YAML file to Salesforce Semantic Model JSON format:

```bash
java -jar target/osi-salesforce-converter-0.1.0-SNAPSHOT.jar toSF input.yaml
# Output: Customer_Orders_Model.json (named after model's 'apiName' field)
# Created in the same directory as the input file
```

Example:
```bash
java -jar target/osi-salesforce-converter-0.1.0-SNAPSHOT.jar toSF \
  src/test/resources/examples/osiToSalesforce.yaml
# Output: src/test/resources/examples/Customer_Orders_Model.json
```

### Programmatic API

#### String Conversion

```java
import org.osi.converter.Converter;
import org.osi.converter.ConverterFactory;
import org.osi.converter.ConversionDirection;

Converter sfToOsi = ConverterFactory.getConverter(ConversionDirection.SALESFORCE_TO_OSI);
List<String> osiYamlList = sfToOsi.convert(salesforceJsonString);
String osiYaml = osiYamlList.get(0);

Converter osiToSf = ConverterFactory.getConverter(ConversionDirection.OSI_TO_SALESFORCE);
List<String> salesforceJsonList = osiToSf.convert(osiYamlString);
```

#### File Conversion

```java
import org.osi.converter.Converter;
import org.osi.converter.ConverterFactory;
import org.osi.converter.ConversionDirection;

import java.nio.file.Paths;

Converter sfToOsi = ConverterFactory.getConverter(ConversionDirection.SALESFORCE_TO_OSI);
sfToOsi.convert(Paths.get("input/model.json"), Paths.get("output/"));

Converter osiToSf = ConverterFactory.getConverter(ConversionDirection.OSI_TO_SALESFORCE);
osiToSf.convert(Paths.get("input/model.yaml"), Paths.get("output/"));
```

### Features

- **Schema-validated** - Input is validated against JSON Schema before processing
- **Lossless conversion** - Unmapped properties are preserved in `custom_extensions`
- **Bidirectional** - Full bi-directional conversion without data loss
- **Supports OSI Specification v0.2.0.dev0**

## Mapping Reference

### Import (Salesforce → OSI)

| Salesforce | OSI |
|------------|-----|
| `apiName` | `name` |
| `semanticDataObjects[]` | `datasets[]` |
| `semanticDataObjects[].apiName` | `datasets[].name` |
| `semanticDataObjects[].dataObjectName` | `datasets[].source` |
| `semanticDimensions[]` + `semanticMeasurements[]` | `fields[]` |
| `dataObjectFieldName` | `expression.dialects[].expression` |
| `semanticRelationships[]` | `relationships[]` |
| `criteria[]` | `from_columns` + `to_columns` |
| `semanticCalculatedMeasurements[]` | `metrics[]` |
| `semanticCalculatedDimensions[]` | Converted to `fields[]` if single data object dependency, otherwise stored in `custom_extensions` |
| `businessPreferences` | `ai_context` |
| Unmapped properties | `custom_extensions` (vendor: `SALESFORCE`) |

### Export (OSI → Salesforce)

| OSI | Salesforce |
|-----|------------|
| `name` | `apiName` |
| `datasets[]` | `semanticDataObjects[]` |
| `datasets[].name` | `semanticDataObjects[].apiName` |
| `datasets[].source` | `semanticDataObjects[].dataObjectName` |
| `fields[]` | Split into `semanticDimensions[]` and `semanticMeasurements[]` based on `expression` analysis |
| `expression.dialects[].expression` | `dataObjectFieldName` |
| `relationships[]` | `semanticRelationships[]` |
| `from_columns` + `to_columns` | `criteria[]` |
| `metrics[]` | `semanticCalculatedMeasurements[]` |
| `ai_context` | `businessPreferences` |
| `custom_extensions` (vendor: `SALESFORCE`) | Restored properties |

### Type Detection (Export)

Fields are automatically classified as dimensions or measurements based on expression analysis:

- **Measurements** — expressions containing SQL aggregation functions (`SUM`, `COUNT`, `AVG`, etc.)
- **Dimensions** — all other fields
- **Time dimensions** — Date/DateTime types set `dimension.is_time: true`

### Relationship Handling

**Unsupported relationships** (containing Formula or SemanticField types) are stored in `custom_extensions` at the model level rather than being converted to OSI relationships.

## Architecture

```
                    ┌───────────────────────┐
                    │ OsiSalesforceConverter│
                    │      (CLI App)        │
                    └───────────┬───────────┘
                            │
                    ┌───────┴────────┐
                    │ ConverterFactory│
                    └───────┬────────┘
                            │
              ┌─────────────┴─────────────┐
              │      ConverterImpl        │
              │   (Pipeline-based)        │
              │                           │
              │ • Configurable pipeline   │
              │ • Bidirectional mapping   │
              └─────────────┬─────────────┘
                            │
              ┌─────────────┴─────────────┐
              │    Pipeline Handlers      │
              ├───────────────────────────┤
              │ • DatasetMappingHandler   │
              │ • FieldMappingHandler     │
              │ • RelationshipHandler     │
              │ • MetricMappingHandler    │
              │ • SemanticModelHandler    │
              └─────────────┬─────────────┘
                            │
              ┌─────────────┴─────────────┐
              │   Support Components      │
              ├───────────────────────────┤
              │ • GenericMappingEngine    │
              │ • CustomExtensionHandler  │
              │ • SchemaValidator         │
              └───────────────────────────┘
```

**ConverterFactory** — Creates converter instances for specified direction

**Pipeline Configuration** — Handlers and direction-specific settings defined in `osi-salesforce-converter-config.yaml`

**GenericMappingEngine** — Path-based property mapping using `mappings.yaml` configuration

**CustomExtensionHandler** — Preserves unmapped Salesforce properties in OSI's `custom_extensions` for lossless bi-directional conversion

**SchemaValidator** — Validates input against JSON schemas before conversion

## Examples

See the test suite for sample models demonstrating various features:
- `src/test/resources/examples/osiToSalesforce.yaml` - OSI model example
- `src/test/java/org/osi/OsiToSalesforceConverterTest.java` - OSI to Salesforce conversion tests
- `src/test/java/org/osi/SalesforceToOsiConverterTest.java` - Salesforce to OSI conversion tests

## License

Apache License 2.0 — see [LICENSE](../../LICENSE).
