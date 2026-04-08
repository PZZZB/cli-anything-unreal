#include "CliAnythingBridgeLibrary.h"

#include "Materials/Material.h"
#include "Materials/MaterialInterface.h"
#include "MaterialShared.h"
#include "RHIShaderPlatform.h"

#include "LevelEditor.h"
#include "SLevelViewport.h"
#include "Modules/ModuleManager.h"
#include "Framework/Application/SlateApplication.h"

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

FIntVector4 UCliAnythingBridgeLibrary::GetActiveViewportScreenBounds()
{
	FIntVector4 Bounds(0, 0, 0, 0);

	if (!FModuleManager::Get().IsModuleLoaded("LevelEditor"))
	{
		return Bounds;
	}

	FLevelEditorModule& LevelEditorModule = FModuleManager::GetModuleChecked<FLevelEditorModule>("LevelEditor");
	TSharedPtr<ILevelEditor> ActiveLevelEditor = LevelEditorModule.GetFirstLevelEditor();
	
	if (!ActiveLevelEditor.IsValid())
	{
		return Bounds;
	}

	TSharedPtr<SLevelViewport> ActiveViewport = ActiveLevelEditor->GetActiveViewportInterface();
	if (!ActiveViewport.IsValid())
	{
		return Bounds;
	}

	FGeometry ViewportGeometry = ActiveViewport->GetCachedGeometry();
	FVector2D AbsolutePosition = ViewportGeometry.GetAbsolutePositionAtCoordinates(FVector2D(0.0f, 0.0f));
	FVector2D AbsoluteSize = ViewportGeometry.GetAbsoluteSize();

	Bounds.X = FMath::RoundToInt(AbsolutePosition.X);
	Bounds.Y = FMath::RoundToInt(AbsolutePosition.Y);
	Bounds.Z = FMath::RoundToInt(AbsoluteSize.X);
	Bounds.W = FMath::RoundToInt(AbsoluteSize.Y);

	return Bounds;
}
