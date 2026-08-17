"""Small, immediate collaboration topologies above the technical runtime."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .types import require_agent_name


@dataclass(frozen=True, slots=True)
class RecipeRole:
    """One stable role admitted by a collaboration recipe."""

    name: str
    agent_type: str
    default_replicas: int = 1
    maximum_replicas: int = 1
    scalable: bool = False

    def __post_init__(self) -> None:
        require_agent_name(self.name, field_name="recipe role")
        require_agent_name(self.agent_type, field_name="recipe agent type")
        if (
            type(self.default_replicas) is not int
            or type(self.maximum_replicas) is not int
            or self.default_replicas < 1
            or self.maximum_replicas < self.default_replicas
        ):
            raise ValueError("recipe replica bounds must be positive and ordered")
        if not self.scalable and (
            self.default_replicas != 1 or self.maximum_replicas != 1
        ):
            raise ValueError("a non-scalable recipe role must have exactly one replica")
        if type(self.scalable) is not bool:
            raise TypeError("recipe scalable must be a bool")


@dataclass(frozen=True, slots=True)
class CollaborationRecipe:
    """A bounded topology name and its Product-visible roles."""

    recipe_id: str
    description: str
    roles: tuple[RecipeRole, ...]

    def __post_init__(self) -> None:
        require_agent_name(self.recipe_id, field_name="recipe id")
        if not self.description.strip():
            raise ValueError("recipe description must be non-empty")
        roles = tuple(self.roles)
        if not roles:
            raise ValueError("a collaboration recipe must declare at least one role")
        names = tuple(role.name for role in roles)
        if len(set(names)) != len(names):
            raise ValueError("recipe role names must be unique")
        object.__setattr__(self, "roles", roles)

    def role(self, name: str) -> RecipeRole | None:
        return next((role for role in self.roles if role.name == name), None)


class CollaborationRecipeCatalog:
    """Immutable catalog with collision rejection at admission time."""

    def __init__(self, recipes: Iterable[CollaborationRecipe] = ()) -> None:
        values: dict[str, CollaborationRecipe] = {}
        for recipe in recipes:
            if recipe.recipe_id in values:
                raise ValueError(f"duplicate collaboration recipe: {recipe.recipe_id}")
            values[recipe.recipe_id] = recipe
        self._recipes: Mapping[str, CollaborationRecipe] = MappingProxyType(values)

    def resolve(self, recipe_id: str) -> CollaborationRecipe | None:
        return self._recipes.get(recipe_id)

    def values(self) -> tuple[CollaborationRecipe, ...]:
        return tuple(self._recipes[key] for key in sorted(self._recipes))


def core_recipe_catalog() -> CollaborationRecipeCatalog:
    """Return the two useful phase-one immediate collaboration recipes."""

    return CollaborationRecipeCatalog(
        (
            CollaborationRecipe(
                recipe_id="parallel-review",
                description=(
                    "Run independent read-only reviewers in parallel, then synthesize."
                ),
                roles=(
                    RecipeRole(
                        name="reviewer",
                        agent_type="reviewer",
                        default_replicas=2,
                        maximum_replicas=3,
                        scalable=True,
                    ),
                    RecipeRole(name="synthesizer", agent_type="synthesizer"),
                ),
            ),
            CollaborationRecipe(
                recipe_id="debate",
                description=(
                    "Run a proposer, critic, and impartial judge in sequence."
                ),
                roles=(
                    RecipeRole(name="proposer", agent_type="proposer"),
                    RecipeRole(name="critic", agent_type="critic"),
                    RecipeRole(name="judge", agent_type="judge"),
                ),
            ),
        )
    )


__all__ = [
    "CollaborationRecipe",
    "CollaborationRecipeCatalog",
    "RecipeRole",
    "core_recipe_catalog",
]
