#include "CliAnythingBridgeLibrary.h"
#include "Materials/Material.h"
#include "Materials/MaterialInterface.h"
#include "MaterialShared.h"
#include "RHIShaderPlatform.h"

TArray<FString> UCliAnythingBridgeLibrary::GetMaterialCompileErrors(UMaterialInterface* Material)
{
	TArray<FString> Result;
	if (!Material)
	{
		return Result;
	}

	UMaterial* BaseMat = Material->GetMaterial();
	if (!BaseMat)
	{
		return Result;
	}

	const EShaderPlatform Platform = GMaxRHIShaderPlatform;

	for (int32 QualityLevel = 0; QualityLevel < EMaterialQualityLevel::Num; ++QualityLevel)
	{
		const FMaterialResource* Resource = BaseMat->GetMaterialResource(
			Platform,
			static_cast<EMaterialQualityLevel::Type>(QualityLevel));

		if (!Resource)
		{
			continue;
		}

		for (const FString& Error : Resource->GetCompileErrors())
		{
			Result.AddUnique(Error);
		}
	}

	return Result;
}
