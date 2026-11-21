# Recipe Enhancement Platform

Automatically enhances recipes by analyzing and applying community-tested modifications from AllRecipes.com. Uses LLM processing to extract meaningful recipe tweaks and apply them with full citation tracking.

## Installation

This project uses [`uv`](https://docs.astral.sh/uv/) for fast, reliable Python package management.

### Prerequisites

- Python 3.13+
- `uv` package manager

## Setup

```bash
# Install dependencies
uv venv
source .venv/bin/activate
uv pip sync pyproject.toml
```

### Environment Variables

Create a `.env` file in the project root:

```env
OPENROUTER_API_KEY=your-openrouter-api-key-here
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=openai/gpt-6-luna
```

## Usage

### 1. Scrape Recipes (Optional - data already provided)

```bash
uv run python src/scraper_v2.py
```

### 2. Run Recipe Enhancement Pipeline

```bash
cd src

# Test single recipe (chocolate chip cookies)
uv run python test_pipeline.py single

# Process all recipes
uv run python test_pipeline.py all

# Route a saved Stage 3 proposal against a saved scrape (offline)
uv run python test_pipeline.py stage4 ../data/recipe.json ../data/stage3-result.json

# Validate a saved Stage 4 result against its scrape (offline)
uv run python test_pipeline.py stage5 ../data/recipe.json ../data/stage4-result.json

# Apply a saved Stage 5 validated plan to its scrape (offline)
uv run python test_pipeline.py stage6 ../data/recipe.json ../data/stage5-result.json

# Generate the final recipe and review evidence from a saved Stage 6 result (offline)
uv run python test_pipeline.py stage7 ../data/stage6-result.json
```

## Output

### Enhanced Recipes

Enhanced recipes are saved in `src/data/enhanced/`:

- `enhanced_[recipe_id]_[recipe-name].json` - Individual enhanced recipes with modifications applied
- `pipeline_summary_report.json` - Summary of all processing results

### Data Structure

Scraped recipe files contain the recipe title, ID, ingredients, instructions, prep/cook/total times, servings, yield, the most helpful positive review, and up to 10 featured tweaks. Reviews and tweaks include their rating, username, date, and helpful-vote count. The enhancement pipeline tries the most helpful review first, then tries featured tweaks in order. Enhanced recipes include:

```json
{
  "recipe_id": "10813_enhanced",
  "title": "Best Chocolate Chip Cookies (Community Enhanced)",
  "ingredients": ["1 cup butter", "1 additional egg yolk", ...],
  "modifications_applied": [
    {
      "source_review": {
        "text": "I added an extra egg yolk for chewier texture",
        "rating": 5
      },
      "modification_type": "addition",
      "reasoning": "Improves texture and chewiness",
      "changes_made": [...]
    }
  ],
  "enhancement_summary": {
    "total_changes": 1,
    "change_types": ["addition"],
    "expected_impact": "Chewier texture and improved consistency"
  }
}
```

## How It Works

The legacy LLM Analysis Pipeline processes recipes in 3 steps:

1. **Tweak Extraction**: Selects one random review with modifications and uses GPT-4o-mini to extract structured changes
2. **Recipe Modification**: Applies changes to the original recipe using fuzzy string matching
3. **Enhanced Recipe Generation**: Creates enhanced version with full citation tracking back to source review

Stage 4 accepts a raw scrape and saved Stage 3 result as local JSON files. It routes modification groups by exact normalized IDs without making model calls.

Stage 5 accepts a raw scrape and saved Stage 4 result as local JSON files. It verifies evidence and grouped edits, prints validation diagnostics, and returns status `continue` with the next ranked review when every modification is rejected. The command does not call a model provider; exit code 3 signals that the caller should continue candidate processing.

Stage 6 accepts the same raw scrape and a saved Stage 5 result. It prints the detached resulting recipe, actual edits, and review evidence. Exit code 0 means the plan was applied or the recipe is unchanged, 1 means the run failed, and 3 signals that candidate processing should continue. A failed application includes the rejected operation in the diagnostics.

Stage 7 reads the saved Stage 6 result and prints final JSON. An `enhanced` result includes the complete recipe and its applied edits with verbatim review evidence and reported or inferred benefits. An `unchanged` result includes the source recipe and a reason. Both exit with code 0. A `failed` result preserves diagnostics and exits with code 1. A `continue` result carries the next candidate for the caller and exits with code 3.

## Development

```bash
# Add dependencies
uv add <package_name>

# Run tests
cd src && uv run python test_pipeline.py single
```
