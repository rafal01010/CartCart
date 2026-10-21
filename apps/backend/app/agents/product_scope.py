from app.agents.contracts import ProductAnalysisAgentInput


def candidate_analysis_category(input_data: ProductAnalysisAgentInput) -> str:
    category = input_data.product.category
    return (
        " ".join(category.split())
        if category and category.strip()
        else "general product"
    )
