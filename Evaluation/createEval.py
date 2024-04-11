#%%
from factorySim.creation import FactoryCreator
import factorySim.baseConfigs as baseConfigs
from factorySim.factorySimClass import FactorySim
from tqdm.auto import tqdm
import os
import ifcopenshell
from ifcopenshell.api import run

factoryConfig = baseConfigs.SMALLSQUARE



if __name__ == "__main__":

    print("Creating Factory")
    basePath = os.path.join(os.path.dirname(os.path.realpath(__file__)))
    outputPath = os.path.join(basePath, "Output")
    #Create directory if it does not exist
    ifcPath = os.path.join(basePath, "..","Input", "2")
    print(ifcPath)

    factory = FactorySim(path_to_ifc_file=ifcPath,factoryConfig=factoryConfig, randSeed=0, createMachines=False)
    print(factory.machine_dict)


    # #save line to json
    # with open("factory.pkl", "wb") as f:
    #     pickle.dump(factory.machine_dict, f)
    

#%%

ifc_file = ifcopenshell.open(os.path.join(ifcPath, "Basic.ifc"))
# %%
import ifcopenshell
from ifcopenshell.api import run

# Create a blank model
model = ifcopenshell.file()

# All projects must have one IFC Project element
project = run("root.create_entity", model, ifc_class="IfcProject", name="My Project")

# Geometry is optional in IFC, but because we want to use geometry in this example, let's define units
# Assigning without arguments defaults to metric units
run("unit.assign_unit", model)

# Let's create a modeling geometry context, so we can store 3D geometry (note: IFC supports 2D too!)
context = run("context.add_context", model, context_type="Model")

# In particular, in this example we want to store the 3D "body" geometry of objects, i.e. the body shape
body = run("context.add_context", model, context_type="Model",
    context_identifier="Body", target_view="MODEL_VIEW", parent=context)

# Create a site, building, and storey. Many hierarchies are possible.
site = run("root.create_entity", model, ifc_class="IfcSite", name="My Site")
building = run("root.create_entity", model, ifc_class="IfcBuilding", name="Building A")
storey = run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Ground Floor")

# Since the site is our top level location, assign it to the project
# Then place our building on the site, and our storey in the building
run("aggregate.assign_object", model, relating_object=project, product=site)
run("aggregate.assign_object", model, relating_object=site, product=building)
run("aggregate.assign_object", model, relating_object=building, product=storey)

# Let's create a new wall
wall = run("root.create_entity", model, ifc_class="IfcWall")

# Give our wall a local origin at (0, 0, 0)
run("geometry.edit_object_placement", model, product=wall)

# Add a new wall-like body geometry, 5 meters long, 3 meters high, and 200mm thick
representation = run("geometry.add_wall_representation", model, context=body, length=5, height=3, thickness=0.2)
# Assign our new body geometry back to our wall
run("geometry.assign_representation", model, product=wall, representation=representation)

# Place our wall in the ground floor
run("spatial.assign_container", model, relating_structure=storey, products=[wall],)


# Write out to a file
model.write("model.ifc")
# %%
