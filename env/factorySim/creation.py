import math
import numpy as np
import pandas as pd
from shapely.geometry import box, MultiPoint, Polygon, MultiPolygon
from shapely.affinity import rotate, scale, translate
from shapely.ops import unary_union
from shapely.prepared import prep
import ifcopenshell
from ifcopenshell.api import run
from factorySim.factoryObject import FactoryObject
from factorySim.utils import prepare_for_export
from factorySim.utils import write_ifc_class


class FactoryCreator():


    def __init__(self, factoryDimensions=(32000,18000), maxShapeWidth=3000, maxShapeHeight=2000, amountRect=20, amountPoly=5, maxCorners=3, randSeed=None):
        self.rng = np.random.default_rng(randSeed)
        self.factoryWidth = factoryDimensions[0]
        self.factoryHeight = factoryDimensions[1]
        self.maxShapeWidth = maxShapeWidth
        self.maxShapeHeight = maxShapeHeight
        self.amountRect = amountRect
        self.amountPoly = amountPoly
        self.maxCorners = maxCorners
        self.bb = None
        self.prep_bb = None
        self.machine_dict = {}
        self.wall_dict = {}

    def suggest_factory_view_scale(self, viewport_width, viewport_height):

        if self.bb:
            bbox = self.bb.bounds #bbox is a tuple of (xmin, ymin, xmax, ymax)
            scale_x = viewport_width / (bbox[2] - bbox[0])
            scale_y = viewport_height / (bbox[3] - bbox[1])
            sugesstedscale = min(scale_x, scale_y)
            return sugesstedscale
        else:
            print("Load a factory first")
            return 0


    def create_factory(self):
        
        polygons = []
        self.machine_dict = {}
        if not self.bb:
            self.bb = box(0,0,self.factoryWidth,self.factoryHeight)
            self.prep_bb = prep(self.bb)

        topLeftCornersRect = self.rng.integers([0,0], [self.factoryWidth - self.maxShapeWidth, self.factoryHeight - self.maxShapeHeight], size=[self.amountRect,2], endpoint=True)
        topLeftCornersPoly = self.rng.integers([0,0], [self.factoryWidth - self.maxShapeWidth, self.factoryHeight - self.maxShapeWidth], size=[self.amountPoly,2], endpoint=True)

        
        #Create Recangles
        for x,y in topLeftCornersRect:
            singlePoly = box(x,y,x + self.rng.integers(self.maxShapeWidth*0.2, self.maxShapeWidth+1), y + self.rng.integers(self.maxShapeHeight*0.2, self.maxShapeHeight+1))
            singlePoly= rotate(singlePoly, self.rng.choice([0,90,180,270]))  
            polygons.append(singlePoly)

        #Create Convex Polygons
        for x,y in topLeftCornersPoly: 
            corners = []
            corners.append([x,y]) # First Corner
            for _ in range(self.rng.integers(2,self.maxCorners+1)):
                corners.append([x + self.rng.integers(self.maxShapeWidth*0.2, self.maxShapeWidth+1), y + self.rng.integers(self.maxShapeWidth*0.2, self.maxShapeWidth+1)])

            singlePoly = MultiPoint(corners).minimum_rotated_rectangle
            singlePoly= rotate(singlePoly, self.rng.integers(0,361))  
            #Filter Linestrings
            if singlePoly.geom_type ==  'Polygon':
            #Filter small Objects
                if singlePoly.area > self.maxShapeWidth*self.maxShapeWidth*0.05:
                    polygons.append(singlePoly)

        union = unary_union(polygons)
        while union.geom_type != 'MultiPolygon':
            corner = self.rng.integers([0,0], [self.factoryWidth - self.maxShapeWidth, self.factoryHeight - self.maxShapeHeight], size=[2], endpoint=True)
            newRect = box(corner[0],corner[1],corner[0] + self.rng.integers(1, self.maxShapeWidth+1), corner[1] + self.rng.integers(1, self.maxShapeHeight+1))
            union = MultiPolygon([union,newRect])

        #origin is lower left corner in shapely
        # Flip on y because Pygames origin is in the top left corner
        multi = MultiPolygon(scale(union, yfact=-1, origin=self.bb.centroid))
        
        for i, poly in enumerate(multi.geoms):
            bbox = poly.bounds
            poly = MultiPolygon([poly])
            #origin is lower left corner
            self.machine_dict[str(i)] = FactoryObject(gid=str(i), 
                                            name="M_" + str(i),
                                            origin=(bbox[0],bbox[1]),
                                            poly=poly,
                                            color=self.rng.random(size=3)
                                            )
        
        

        return self.machine_dict


        return self.multi, self.bb
    def load_dxf_factory(self, filename):
        # Broken TODO
        import ezdxf
        from ezdxf.addons import geo
        from shapely.geometry import shape
        doc = ezdxf.readfile(filename)
        geo_proxy = geo.proxy(doc.modelspace())
        self.multi = shape(geo_proxy)
        #find maximum width and height of factory
        bounds = self.multi.bounds
        self.bb = box(0,0,bounds[2],bounds[3])
        self.prep_bb = prep(self.bb)

        return self.multi, self.bb



    def load_ifc_factory(self, ifc_file_path: str, elementName: str, maxMFElements: int =None, recalculate_bb: bool =False) -> dict:
        """Load a factory element dict from an IFC file

        Args:
            ifc_file_path (str): Path to the IFC file
            elementName (str): IFC Element Name to load
            maxMFElements (int, optional): How many Elements to load (for reinforcement learning training purposes). Defaults to None.
            recalculate_bb (bool, optional): Optionally recalulate the bounding box of the factory using a union of all loaded elements. Defaults to False.

        Returns:
            dict: _description_
        """
        ifc_file = ifcopenshell.open(ifc_file_path)
        element_dict = {}
        elements = []
        if(maxMFElements): 
            ifc_elements = ifc_file.by_type(elementName)
            amount = self.rng.integers(2, maxMFElements+1)
            selected = self.rng.choice(np.arange(len(ifc_elements)-1), size=amount, replace=False)
            elements = [ifc_elements[i] for i in selected]
        else:
            elements = ifc_file.by_type(elementName)
        for index, element in enumerate(elements):
            #get origin
            origin = element.ObjectPlacement.RelativePlacement.Location.Coordinates
            #element.ObjectPlacement.RelativePlacement.Axis.DirectionRatios[0]
            #element.ObjectPlacement.RelativePlacement.RefDirection.DirectionRatios[0]

            #get rotation
            x = element.ObjectPlacement.RelativePlacement.RefDirection.DirectionRatios[0]
            y = element.ObjectPlacement.RelativePlacement.RefDirection.DirectionRatios[1]
            rotation = math.atan2(y,x)
            my_uuid = ""
            if(maxMFElements):
                my_uuid= "_" + str(index)

            #points = element.Representation.Representations[0].Items[0].Outer.CfsFaces[0].Bounds[0].Bound.Polygon
            #Always choose Representation 0
            items = element.Representation.Representations[0].Items

            #Parse imported data into Factory Object (Machine, Wall, ...)
  
            result = []

            for item in items:
                faces = item.Outer.CfsFaces
                facelist = []

                for face in faces:
                    exterior = []
                    interior = []
                    bounds = face.Bounds
                    for bound in bounds:
                        type = bound.get_info()['type']
                        points = bound.Bound.Polygon
                        #Remove z Dimension of Polygon Coordinates
                        pointlist = [(point.Coordinates[0], point.Coordinates[1]) for point in points ]
                        #Check if face is a surface or a hole
                        if (type == "IfcFaceBound"):
                            interior.append(pointlist)
                        else:
                            #Case surface
                            exterior = pointlist

                    facelist.append(Polygon(exterior, interior))
                
                result.append(MultiPolygon(facelist))


            singleElement = unary_union(result)
            if singleElement.type != "MultiPolygon":
                singleElement = MultiPolygon([singleElement])
            #Fix coordinates, since ifc does not save geometry at the correct position
            singleElement = translate(singleElement, origin[0], origin[1])
            singleElement = rotate(singleElement, rotation, origin=(origin[0], origin[1]), use_radians=True)
            #create Factory Object       
            
            name = element.Name if element.Name else element.GlobalId
            element_dict[element.GlobalId] = FactoryObject(gid=element.GlobalId, 
                                                            name=name + my_uuid,
                                                            origin=(origin[0], origin[1]),
                                                            poly=singleElement,
                                                            color=self.rng.random(size=3)
                                                            )
        del(ifc_file)  #Hopefully fixes memory leak

        if recalculate_bb:
            bbox = unary_union([x.poly for x in element_dict.values()])
            #Prevent error due to single element in IFC File
            if bbox.type == "MultiPolygon":
                bbox = bbox.bounds
            else:
                bbox = MultiPolygon([bbox]).bounds
            self.bb = box(bbox[0], bbox[1], bbox[2], bbox[3])
            self.prep_bb = prep(self.bb)
            self.factoryWidth = bbox[2] - bbox[0]
            self.factoryHeight = bbox[3] - bbox[1]

        for element in element_dict.values():
            element.poly = scale(element.poly, yfact=-1, origin=self.bb.centroid)
            polybbox = element.poly.bounds
            element.origin = (polybbox[0], polybbox[1])
            element.center = element.poly.representative_point()
        
        if elementName == "IFCBUILDINGELEMENTPROXY":
            self.machine_dict = element_dict
        elif elementName == "IFCWALL":
            self.wall_dict = element_dict


        return element_dict


    def createRandomMaterialFlow(self, machine_dict: dict = None) -> pd.DataFrame:
        names = []

        if machine_dict is None:
            machine_dict = self.machine_dict

        for start in machine_dict.values():
            sample = start
            while sample == start:
                sample = self.rng.choice(list(self.machine_dict.values()))
            names.append([start.name, sample.name]) 
            if self.rng.random() >= 0.9:
                sample = self.rng.choice(list(self.machine_dict.values()))
                names.append([start.name, sample.name])                 
        self.dfMF = pd.DataFrame(data=names, columns=["source", "target"])
        self.dfMF['intensity'] = self.rng.integers(1,100, size=len(self.dfMF))

        return self.dfMF



    def save_ifc_factory(self, ifc_file_path:str , element_dicts: dict = None, bb: Polygon=None) -> None:

        if element_dicts is None:
            element_dicts = {"IfcBuildingElementProxy": self.machine_dict, 
                             "IfcWall": self.wall_dict
                            }
        if bb is None:    
            bb = self.bb

        # Create a blank model
        model = ifcopenshell.file()

        project = run("root.create_entity", model, ifc_class="IfcProject", name="FactorySim Project")
        # define units
        length = run("unit.add_si_unit", model, unit_type="LENGTHUNIT", prefix="MILLI")
        run("unit.assign_unit", model, units=[length])

        # Create a modeling geometry context, so we can store 3D geometry 
        model3d = run("context.add_context", model, context_type="Model")
        #plan  = run("context.add_context", model, context_type="Plan")
        body = run("context.add_context", model, context_type="Model",
            context_identifier="Body", target_view="PLAN_VIEW", parent=model3d)

        # Create a site, building, and storey. Many hierarchies are possible.
        site = run("root.create_entity", model, ifc_class="IfcSite", name="IfcSite")
        building = run("root.create_entity", model, ifc_class="IfcBuilding", name="IfcBuilding")
        storey = run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="IfcBuildingStorey")

        # Spatially assign the site, building, and storey
        run("aggregate.assign_object", model, relating_object=project, product=site)
        run("aggregate.assign_object", model, relating_object=site, product=building)
        run("aggregate.assign_object", model, relating_object=building, product=storey)

        for ifcElementName, element_dict in element_dicts.items():
            export = prepare_for_export(element_dict, bb)
            elements = write_ifc_class(model, body, ifcElementName, export)
            run("spatial.assign_container", model, relating_structure=storey, products=elements)


        # Write out to a file
        model.write(ifc_file_path)


    def save_position_json(self, filename: str) -> None:
        """Saves all machine positions to a json file

        Args:
            filename (str): path to json file to save machine positions
        """
        import json
        data = {}
        for key, value in self.machine_dict.items():
            data[key] = {"position": value.origin, "rotation": value.rotation}
        with open(filename, 'w') as f:
            json.dump(data, f)

    def load_position_json(self, filename: str) -> None:
        """Loads machine positions from a json file

        Args:
            filename (str): path to json file with machine positions
            format: {"1": {"position": (0,0), "rotation": 0}, "2": {"position": (100,100), "rotation": 3.1244}}
        """
        import json
        with open(filename, 'r') as f:
            data = json.load(f)
            self.set_positions(data)

    def load_positions(self, positions: dict) -> None:
        """Loads machine positions from a dictionary

        Args:
            positions (dict): dictory with keys as machine ids and values as dictionaries with keys "position" and "rotation" (in radians)
            e.g. {"1": {"position": (0,0), "rotation": 0}, "2": {"position": (100,100), "rotation": 3.1244}}

        """
        for key, value in positions.items():
            print(key, type(key))
            machine = self.machine_dict.get(key,None)
            if machine:
                machine.rotate_Item(value["rotation"])
                machine.translate_Item(*value["position"])