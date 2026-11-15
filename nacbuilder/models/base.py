from pydantic import BaseModel, ConfigDict


class NacModel(BaseModel):
    """Base for all data-model sections.

    Field names match the NaC VXLAN schema keys exactly, so `to_nac()` output can be
    written straight into a `*.nac.yaml` file.
    """

    # coerce_numbers_to_str: imported YAML often has unquoted all-digit serials or names.
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, validate_assignment=True, coerce_numbers_to_str=True
    )

    def to_nac(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)
