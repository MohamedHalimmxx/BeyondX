"""Input validation for brand brief — catches bad inputs before the pipeline runs."""


class BrandBriefValidationError(Exception):
    pass


def validate_brand_brief(
    idea: str,
    location: str,
    differentiator: str,
    ideal_customer: str,
    non_negotiable: str,
) -> None:
    """
    Validates brand brief inputs. Raises BrandBriefValidationError with
    a clear message if any field fails.
    """
    errors = []

    if len(idea.strip()) < 10:
        errors.append("Business idea is too short — describe your concept in at least 10 characters.")

    if len(location.strip()) < 3:
        errors.append("Location must include a city and country (e.g. 'Cairo, Egypt').")

    weak_differentiators = {"quality", "service", "best", "great", "affordable", "cheap", "good"}
    diff_words = set(differentiator.lower().split())
    if len(differentiator.strip()) < 15:
        errors.append("Differentiator is too vague — be specific about what makes you different.")
    elif diff_words.issubset(weak_differentiators):
        errors.append("Differentiator uses generic words (quality, service, best). Be specific.")

    if len(ideal_customer.strip()) < 15:
        errors.append("Ideal customer description is too short — describe a specific person.")

    if len(non_negotiable.strip()) < 10:
        errors.append("Non-negotiable is too short — what is the ONE thing you will never compromise on?")

    if errors:
        raise BrandBriefValidationError(
            "\n".join([f"  ⚠️  {e}" for e in errors])
        )