#!/usr/bin/env python3

import os
import math
import random
from itertools import combinations
from time import time

import numpy as np

import cairo
import pandas as pd
from shapely.geometry import  Polygon,  MultiPolygon

from factorySim.creation import FactoryCreator
import factorySim.baseConfigs as baseConfigs


class FactorySim:
 #------------------------------------------------------------------------------------------------------------
 # Loading
 #------------------------------------------------------------------------------------------------------------
    def __init__(self, path_to_ifc_file=None, path_to_materialflow_file = None, factoryConfig=baseConfigs.SMALL, randseed = None, randomPos = False,  verboseOutput = 0, maxMF_Elements = None, objectScaling = 1.0):
        self.FACTORYDIMENSIONS = (factoryConfig.WIDTH, factoryConfig.HEIGHT) # if something is read from file this is overwritten
        self.MAXMF_ELEMENTS = maxMF_Elements
        self.factoryCreator = FactoryCreator(*factoryConfig.creationParameters())
        self.verboseOutput = verboseOutput
        self.RANDSEED = randseed
        random.seed(randseed)
            
        self.timezero = time()
        self.lasttime = 0

        if(os.path.isdir(path_to_ifc_file)):
            
            self.ifc_file = random.choice([x for x in os.listdir(path_to_ifc_file) if ".ifc" in x and "LIB" not in x])
            self.ifc_file = os.path.join(path_to_ifc_file, self.ifc_file)
        else:
            self.ifc_file = path_to_ifc_file
            
        if(self.verboseOutput >= 2):
            print("Lade: ", self.ifc_file)

        if(self.verboseOutput >= 3):
            self.printTime("Datei geladen")

        #Importing Machines
        if path_to_ifc_file:
            if(self.MAXMF_ELEMENTS):
                path = os.path.join(os.path.dirname(self.ifc_file), "MFO_LIB.ifc")
                if(os.path.exists(path)):
                    mfo_ifc_file_path = path
                else:
                    mfo_ifc_file_path = self.ifc_file

                if(self.verboseOutput >= 2):
                    print(f"Lade: Demomaterialflussobjekte. Maximal {self.MAXMF_ELEMENTS} werden aus {mfo_ifc_file_path} geladen.")
                #2 bis MAXMF_ELEMENTS aus der Datei mit Demomaterialflussobjekten laden.
                self.machine_dict = self.factoryCreator.load_ifc_factory(mfo_ifc_file_path, "IFCBUILDINGELEMENTPROXY", randomMF=self.MAXMF_ELEMENTS)
            else:
                if(self.verboseOutput >= 2):
                    print("Nutze alle MF Objekte in der IFC Datei")
                self.machine_dict = self.factoryCreator.load_ifc_factory(self.ifc_file, "IFCBUILDINGELEMENTPROXY")

            #Set factory size accordint to what we have loaded from file:
            bbox = self.factoryCreator.bb.bounds
            self.FACTORYDIMENSIONS = (bbox[2], bbox[3])

        #Random Machines if nothing to import
        else:
            self.machine_dict = self.factoryCreator.create_factory()

        if(self.verboseOutput >= 1):
            self.printTime(f"IFCBUILDINGELEMENTPROXY geparsed")
        #Importing Walls
        self.wall_list = self.factoryCreator.load_ifc_factory(self.ifc_file, "IFCWALL") 
        self.machineCollisionList = []
        self.wallCollisionList = []

        self.lastRating = 0
        self.currentRating    = 0 # Holds the Rating of the current state of the Layout 
        self.currentMappedRating    = 0 # Holds the normalized Rating of the current state of the Layout 

        self.lastUpdatedMachine = None #Hold uid of last updated machine for collision checking
        self.collisionAfterLastUpdate = False # True if latest update leads to new collsions

        self.episodeCounter = 0

    
        if(self.verboseOutput >= 3):
            self.printTime("Skaliert")

        #Creating random positions
        if randomPos:
            for key in self.machine_dict:
                self.update(key,
                    xPosition = random.uniform(-1,1),
                    yPosition = random.uniform(-1,1),
                    rotation = random.uniform(-1,1),
                    massUpdate = True)

        #Find Collisions
        self.findCollisions()
        
        #Import Materialflow from Excel
        if path_to_materialflow_file:
            self.materialflow_file = pd.read_csv(path_to_materialflow_file, skipinitialspace=True, encoding= "utf-8")
            #Rename Colums
            indexes = self.materialflow_file.columns.tolist()
            self.materialflow_file.rename(columns={indexes[0]:'from', indexes[1]:'to', indexes[2]:'intensity'}, inplace=True)
        else:
            #Create Random Materialflow
            names = []
            for _ in range(0,len(self.machine_dict) * 2):
                samples = random.sample(list(self.machine_dict.values()), k=2)
                names.append([samples[0].name, samples[1].name]) 
            self.materialflow_file = pd.DataFrame(data=names, columns=["from", "to"])
            self.materialflow_file['intensity'] = np.random.randint(1,100, size=len(self.materialflow_file))

        #Group by from and two, add up intensity of all duplicates in intensity_sum
        self.materialflow_file['intensity_sum'] = self.materialflow_file.groupby(by=['from', 'to'])['intensity'].transform('sum')
        #drop the duplicates and refresh index
        self.materialflow_file = self.materialflow_file.drop_duplicates(subset=['from', 'to']).reset_index(drop=True)
        #normalise intensity sum 
        self.materialflow_file['intensity_sum_norm'] = self.materialflow_file['intensity_sum'] / self.materialflow_file.max()["intensity_sum"]
        #use machine index as sink and source for materialflow
        #Replace Machine Names in Material flow (From Sketchup Import) with machine dict key
        machine_dict = {machine.name: key for key, machine in self.machine_dict.items()}
        self.materialflow_file[['from','to']] = self.materialflow_file[['from','to']].replace(machine_dict)
        #set initial values for costs
        self.materialflow_file['costs'] = 0
    
        if(self.verboseOutput >= 3):
            self.printTime("Materialfluss geladen")


        
 #------------------------------------------------------------------------------------------------------------
 # Update Machines
 #------------------------------------------------------------------------------------------------------------
    def update(self, machineIndex, xPosition = 0, yPosition = 0, rotation = None, skip = 0, massUpdate = False):
        if type(machineIndex) == int:
            if machineIndex< len(self.machine_dict):
                machineIndex = list(self.machine_dict)[machineIndex]
            else:
                print("Machine Index not found")
                return

        if not massUpdate: self.episodeCounter += 1
        if(skip < 0.8):
            self.lastUpdatedMachine = self.machine_dict[machineIndex].gid

            if(self.verboseOutput >= 2):
                print(f"Update: {self.machine_dict[machineIndex].name} - X: {xPosition:1.1f} Y: {yPosition:1.1f} R: {rotation:1.2f} ")

            if (rotation is not None):
                mappedRot = self.mapRange(np.clip(rotation,-1.0, 1.0), (-1,1), (0, 2*math.pi))
                self.machine_dict[machineIndex].rotate_Item(mappedRot)

            #Max Value should move machine to the rightmost or topmost position without moving out of the image
            mappedXPos = self.mapRange(np.clip(xPosition,-1.0, 1.0), (-1,1), (0,self.WIDTH - self.machine_dict[machineIndex].width))
            mappedYPos = self.mapRange(np.clip(yPosition,-1.0, 1.0), (-1,1), (0,self.HEIGHT - self.machine_dict[machineIndex].height))
            #mappedXPos = self.mapRange(xPosition, (-1,1), (0,self.WIDTH))
            #mappedYPos = self.mapRange(yPosition, (-1,1), (0,self.HEIGHT))

            self.machine_dict[machineIndex].translate_Item(mappedXPos, mappedYPos)
            if not massUpdate:
                self.findCollisions()
            if(self.verboseOutput >= 3):
                self.printTime(f"{self.machine_dict[machineIndex].name} geupdated")
        else:
             if(self.verboseOutput >= 2):
                print(f"Update: {self.machine_dict[machineIndex].name} - Skipped Update")


    
 #------------------------------------------------------------------------------------------------------------
 # Evaluation
 #------------------------------------------------------------------------------------------------------------
    def evaluate(self):
        output = {}
        output["ratingMF"] = self.evaluateMF()          
        if(self.verboseOutput >= 3):
            self.printTime("Bewertung des Materialfluss abgeschlossen")
        output["ratingCollision"] = self.evaluateCollision()          
        if(self.verboseOutput >= 3):
            self.printTime("Kollisionsbewertung abgeschlossen")


       
        #if(self.episodeCounter < len(self.machine_list)):
        #    self.currentRating = 0
        #el

        if(output["ratingCollision"] == 1):
            self.currentRating = math.pow(output["ratingMF"],3)
        else: 
            self.currentRating = -1
            #if(output["ratingCollision"] >= 0.5):
            #    self.currentRating = 0.1
            #else:
            #    self.currentRating = -1


        #if(self.collisionAfterLastUpdate):
        #    self.currentRating = -0.8
        #elif(output["ratingCollision"] < 1):
        #    self.currentRating = -0.5
        #else:
        #    self.currentRating = self.mapRange(output["ratingMF"],(-2,1),(-1,1))




        ##Normalize
        #if(self.episodeCounter % len(self.machine_list) == 0 ):
        #    self.currentMappedRating = self.mapRange(self.currentRating,(-2,2),(-1,1))
        #
        #elif(self.currentRating > self.lastRating):
        #    self.currentMappedRating = 0.1
        #else:
        #    self.currentMappedRating = -0.2
        #
        #self.lastRating = self.currentRating



        #self.currentMappedRating = self.mapRange(self.currentRating,(-2,2),(-1,1))
        self.currentMappedRating = output["TotalRating"]= self.currentRating

        #print(f"walls: {len(self.wallCollisionList)}, machines: {len(self.machineCollisionList)}, count m: {len(self.machine_list)}")
        #if(len(self.wallCollisionList) + len(self.machineCollisionList) >=len(self.machine_list)):
        #    done = True
        #else:
        #    done = False


        #if(self.episodeCounter >= 3 * len(self.machine_list)):
        if(self.episodeCounter > len(self.machine_dict)+1):
            done = True
            output["done"] = True
        else:
            done = False     
        #done = False      


        if(self.verboseOutput >= 3):
            self.printTime("Bewertung des Layouts abgeschlossen")
        if(self.verboseOutput >= 1):
            print(f"Total Rating: {self.currentMappedRating:1.2f}\n"
                f"Raw Rating: {self.currentRating:1.2f}\n"
                f"MaterialFlow: {output['ratingMF']:1.2f}\n"
                f"Kollisionen: {output['ratingCollision']:1.2f}")

        return self.currentMappedRating, self.currentRating, output, done

 #------------------------------------------------------------------------------------------------------------
    def evaluateMF_Helper(self, source, sink): 
        source_center = self.machine_dict[source].center
        sink_center = self.machine_dict[sink].center
        return math.sqrt(math.pow(source_center.x-sink_center.x,2) + math.pow(source_center.y-sink_center.y,2))

 #------------------------------------------------------------------------------------------------------------
    def evaluateMF(self):
        self.materialflow_file['distance'] = self.materialflow_file.apply(lambda row: self.evaluateMF_Helper(row['from'], row['to']), axis=1)
        #sum of all costs /  maximum intensity (intensity sum norm * 1) 
        maxDistance = max(self.max_value_x,  self.max_value_y)
        self.materialflow_file['distance_norm'] = self.materialflow_file['distance'] / maxDistance
        self.materialflow_file['costs'] = self.materialflow_file['distance_norm'] * self.materialflow_file['intensity_sum_norm']
        output = 1 - (math.pow(self.materialflow_file['costs'].sum(),2) / self.materialflow_file['intensity_sum_norm'].sum())
        if(output < 0): output = 0

        return output

 #------------------------------------------------------------------------------------------------------------
    def evaluateCollision(self):
        
        #machineCollisionArea = 0
        #wallCollisionArea = 0
        #totalMachineArea = 0
        # 
        #for collision in self.machineCollisionList:
        #    machineCollisionArea += collision.area()
        #for collision in self.wallCollisionList:
        #   wallCollisionArea += collision.area() 
        #for machine in self.machine_list.values():      
        #    totalMachineArea += machine.hull.area()

        #print(len(list(combinations(self.machine_list.values(), 2))))
        nMachineCollisions = len(self.machineCollisionList)
        nWallCollosions = len(self.wallCollisionList)

        #If latest update leads to collision give worst rating.
        #if(self.collisionAfterLastUpdate):
        #    output = -3
        #else:
        #    output = 1 - (0.5 * nMachineCollisions) - (0.5 * nWallCollosions)
    
        output = 1 - (0.5 * nMachineCollisions) - (0.5 * nWallCollosions)
        
        return output


 #------------------------------------------------------------------------------------------------------------
 # Collision Detection
 #------------------------------------------------------------------------------------------------------------
    def findCollisions(self):
        self.collisionAfterLastUpdate = False
        #Machines with Machines
        self.machineCollisionList = []       
        for a,b in combinations(self.machine_dict.values(), 2):
            if a.poly.overlaps(b.poly):
                if(self.verboseOutput >= 4):
                    print(f"Kollision zwischen {a.name} und {b.name} gefunden.")
                col = a.poly.intersection(b.poly)
                if col.type != "MultiPolygon":
                    col = MultiPolygon([col])
                self.machineCollisionList.append(col)
                if(a.gid == self.lastUpdatedMachine or b.gid == self.lastUpdatedMachine): self.collisionAfterLastUpdate = True
        #Machines with Walls     
        self.wallCollisionList = []
        for a in self.wall_list.values():
            for b in self.machine_dict.values():
                if a.poly.overlaps(b.poly):
                    if(self.verboseOutput >= 4):
                        print(f"Kollision Wand {a.name} und Maschine {b.name} gefunden.")
                    col = a.poly.intersection(b.poly)
                    if col.type != "MultiPolygon":
                        col = MultiPolygon([col])
                    self.wallCollisionList.append(col)
                    if(b.gid == self.lastUpdatedMachine): self.collisionAfterLastUpdate = True
                    
        if(self.verboseOutput >= 3):
            self.printTime("Kollisionen berechnen abgeschlossen")

 #------------------------------------------------------------------------------------------------------------
 # Drawing
 #------------------------------------------------------------------------------------------------------------
    def provideCairoDrawingData(self, width, height):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        ctx = cairo.Context(self.surface)
        scale = self.factoryCreator.scale_factory(width, height)
        self.ctx.scale(scale, scale)
        return surface, ctx



#------------------------------------------------------------------------------------------------------------ 
    def drawPositions(self, ctx, scale = 1, drawColors = True, drawMachines = True, drawMaterialflow = True, drawMachineCenter = False, drawOrigin = True, drawWalls = True, highlight = None):   
        #Drawing
        if(surfaceIn is None):
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.WIDTH * scale, self.HEIGHT * scale)
        else:
            surface = surfaceIn
        ctx = cairo.Context(surface)
        #ctx.scale(1.0 * scale, -1.0 * scale)
        #ctx.translate(0.0,-self.HEIGHT)
        if(surfaceIn is None):
            ctx.rectangle(0, 0, self.WIDTH, self.HEIGHT)  
            ctx.set_source_rgb(1.0, 1.0, 1.0)
            ctx.fill()

      #Walls
        if drawWalls:
            ctx.set_fill_rule(cairo.FillRule.EVEN_ODD)
            for wall in self.wall_list.values():
                #draw all walls
                for poly in wall.poly.geoms:
                    ctx.set_source_rgb(0, 0, 0)
                    for point in poly.exterior.coords:  
                        ctx.line_to(point[0], point[1])
                    ctx.close_path()
                    ctx.fill()
                #draw all holes
                    ctx.set_source_rgb(1, 1, 1)
                    for loop in poly.interiors:
                        for point in loop.coords:
                            ctx.line_to(point[0], point[1])
                        ctx.close_path()
                    ctx.fill()
                            
        #draw machine positions
        if drawMachines:
            ctx.set_fill_rule(cairo.FillRule.WINDING)
            ctx.set_line_width(self.DOT_RADIUS)
            for index, machine in enumerate(self.machine_dict.values()):

                for poly in machine.poly.geoms:
                    for point in poly.exterior.coords: 
                        ctx.line_to(point[0], point[1])
                    ctx.close_path()
                    #no highlights
                    if(highlight is None):
                        ctx.set_source_rgb(machine.color[0], machine.color[1], machine.color[2])
                    #highlighted machine
                    elif(index == highlight or machine.gid == highlight):
                        ctx.set_source_rgb(0.9, 0.9, 0.9)
                    #other machines
                    else:
                        ctx.set_source_rgb(0.4, 0.4, 0.4)

                    ctx.fill_preserve()
                    if(drawColors):
                        ctx.set_source_rgb(machine.color[0], machine.color[1], machine.color[2])
                    else:
                        ctx.set_source_rgb(0.5, 0.5, 0.5)
                    ctx.stroke()

            #Machine Centers
                if (drawMachineCenter):
                    ctx.set_source_rgb(0, 0, 0)
                    ctx.arc(machine.center.x, machine.center.y, self.DOT_RADIUS, 0, 2*math.pi)
                    ctx.fill()

            #Machine Origin 
                if (machine.origin is not None and drawOrigin):
                    ctx.set_source_rgb(machine.color[0], machine.color[1], machine.color[2])
                    ctx.arc(machine.origin[0], machine.origin[1], self.DOT_RADIUS, 0, 2*math.pi)
                    ctx.fill()

        #Material Flow
        if drawMaterialflow:

            for index, row in self.materialflow_file.iterrows():
                current_from_Machine = self.machine_dict[row['from']]
                current_to_Machine = self.machine_dict[row['to']]
                try:
                    if(drawColors):
                        ctx.set_source_rgb(*current_from_Machine.color)
                    else:
                        ctx.set_source_rgb(0.6, 0.6, 0.6)

                    ctx.move_to(current_from_Machine.center.x, current_from_Machine.center.y)
                    ctx.line_to(current_to_Machine.center.x, current_to_Machine.center.y)
                    ctx.set_line_width(row["intensity_sum_norm"] * self.MAX_STROKE_WIDTH)
                    ctx.stroke()   
                except KeyError:
                    print(f"Error in Material Flow Drawing - Machine {row[0]} or {row[1]} not defined")
                    continue
        if(self.verboseOutput >= 3):
            self.printTime("Maschinenpositionen gezeichnet")
        del(ctx)
        return surface
    
    
#------------------------------------------------------------------------------------------------------------  
    def drawDetailedMachines(self, surfaceIn=None, scale = 1, randomcolors = False, highlight = None):   
        #Drawing
        #Machine Positions
        if(surfaceIn is None):
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.WIDTH * scale, self.HEIGHT * scale)
        else:
            surface = surfaceIn
        ctx = cairo.Context(surface)
        ctx.scale(1.0 * scale, -1.0 * scale)
        ctx.translate(0.0,-self.HEIGHT)
        if(surfaceIn is None):
            ctx.rectangle(0, 0, self.WIDTH, self.HEIGHT)  
            ctx.set_source_rgb(1.0, 1.0, 1.0)
            ctx.fill()
        
        #draw machine positions
        for i, machine in enumerate(self.machine_dict.values()):
            for poly in machine.poly.geoms:
                if (((i == highlight) or machine.gid==highlight) and (highlight is not None)):
                    ctx.set_source_rgb(machine.color[0], machine.color[1], machine.color[2])
                elif randomcolors:
                        ctx.set_source_rgb(random.random(), random.random(), random.random())
                else:
                    ctx.set_source_rgb(0.4, 0.4, 0.4)
                #draw all outer contours
                for point in poly.exterior.coords:  
                    ctx.line_to(point[0], point[1])
                ctx.close_path()
                ctx.fill()
                #draw all holes
                if randomcolors:
                    ctx.set_source_rgb(random.random(), random.random(), random.random())
                else:
                    ctx.set_source_rgb(machine.color[0], machine.color[1], machine.color[2])
                for loop in poly.interiors:
                    for point in loop.coords:
                        ctx.line_to(point[0], point[1])
                    ctx.close_path()
                ctx.fill()

                
        if(self.verboseOutput >= 3):
            self.printTime("Detailierte Machinenpositionen gezeichnet")
        return surface


 #------------------------------------------------------------------------------------------------------------
    def drawCollisions(self, surfaceIn=None, drawColors = True, scale = 1, drawWalls=True):

        #Machine Collisions
        if(surfaceIn is None):
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.WIDTH * scale, self.HEIGHT * scale)
        else:
            surface = surfaceIn
        ctx = cairo.Context(surface)
        #ctx.scale(1.0 * scale, -1.0 * scale)
        #ctx.translate(0.0,-self.HEIGHT)
        if(surfaceIn is None):
            ctx.rectangle(0, 0, self.WIDTH, self.HEIGHT)  
            ctx.set_source_rgb(1.0, 1.0, 1.0)
            ctx.fill()

        #Drawing collisions between machines
        if(drawColors):
            ctx.set_source_rgb(1.0, 0.3, 0.0)
        else:
            ctx.set_source_rgb(0.7, 0.7, 0.7)

        for collision in self.machineCollisionList:
            for poly in collision.geoms:   
                for point in poly.exterior.coords:
                    ctx.line_to(point[0], point[1])
            ctx.close_path()
            ctx.fill()
                    
        #Drawing collisions between machines and walls
        if(drawWalls):
            if(drawColors):
                ctx.set_source_rgb(1.0, 0.3, 0.0)
            else:
                ctx.set_source_rgb(0.7, 0.7, 0.7)
            for collision in self.wallCollisionList:
                for poly in collision.geoms:   
                    for point in poly.exterior.coords:
                        ctx.line_to(point[0], point[1])
                ctx.close_path()
                ctx.fill()           
                    
        if(self.verboseOutput >= 3):
            self.printTime("Kollisionen gezeichnet")
        del(ctx)
        return surface
 #------------------------------------------------------------------------------------------------------------
 # Helpers  
 #------------------------------------------------------------------------------------------------------------
    
    def printTime(self, text):
        number = (time() - self.timezero - self.lasttime)
        self.lasttime += number
        number = round(number * 1000, 2)
        print(f"{number:6.2f} - {text}")

  #------------------------------------------------------------------------------------------------------------  
    def mapRange(self,s , a, b):
        (a1, a2), (b1, b2) = a, b
        if(s < a1): s = a1
        if(s > a2): s = a2
        return  b1 + ((s - a1) * (b2 - b1) / (a2 - a1))
 #------------------------------------------------------------------------------------------------------------
 # Destructor  
 #------------------------------------------------------------------------------------------------------------
    def __del__(self):
        del(self.machine_dict)
        del(self.wall_list)
        del(self.machineCollisionList)
        del(self.wallCollisionList)
        del(self.materialflow_file)

#------------------------------------------------------------------------------------------------------------
def main():
    outputfile ="Out"

    #filename = "Long"
    filename = "Basic"
    #filename = "Simple"
    #filename = "SimpleNoCollisions"

    ifcpath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 
        "..",
        "..",
        "Input",
        "2",  
        filename + ".ifc")


    file_name, _ = os.path.splitext(ifcpath)
    materialflowpath = file_name + "_Materialflow.csv"
    #materialflowpath = None
    
    demoFactory = FactorySim(ifcpath,
    path_to_materialflow_file = materialflowpath,
    randomMF = True,
    randomPos = True,
    verboseOutput=4,
    maxMF_Elements = None,
    objectScaling=1.0)
    print(demoFactory.machineCollisionList)
    #Machine Positions Output to PNG
    #machinePositions = demoFactory.drawPositions(drawMaterialflow = True, drawMachineCenter = True)
    machinePositions = demoFactory.drawPositions(drawMaterialflow = True, drawMachineCenter = True, highlight=1)
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
        "..",
        "..",
        "Output", 
        F"{outputfile}_machines.png")
    machinePositions.write_to_png(path) 
    demoFactory.printTime("PNG schreiben")
 #------------------------------------------------------------------------------------------------------------------------------------------
    #detailed Machines Output to PNG
    # detailedMachines = demoFactory.drawDetailedMachines(surfaceIn=machinePositions, randomcolors = False, highlight=None)
    # path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
    #     "..",
    #     "..",
    #    "Output", 
    #    F"{outputfile}_detailed_machines.png")
    # detailedMachines.write_to_png(path)
 #------------------------------------------------------------------------------------------------------------------------------------------


    #Rate current Layout
    demoFactory.evaluate()

    #Change machine
    #demoFactory.update(0,demoFactory.machine_list[0].origin.x,demoFactory.machine_list[0].origin.y, math.pi/2)
    demoFactory.update(0,0.8 ,-0.2 , 1)
    demoFactory.evaluate()
    demoFactory.update(1,1 ,-1 , 1)
    demoFactory.evaluate()
    demoFactory.update(1,0.1 ,-0.8 , 1, 0.8)

    machinePositions = demoFactory.drawPositions(drawColors = True, drawMachines=True, drawMaterialflow = True, highlight=1)
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
        "..",
        "..",
        "Output", 
        F"{outputfile}_machines_update.png")
    machinePositions.write_to_png(path) 
    demoFactory.printTime("PNG schreiben")

    #Machine Collisions Output to PNG
    Collisions = demoFactory.drawCollisions(scale = 1, drawColors = True, surfaceIn=machinePositions)
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
        "..",
        "..",
        "Output", 
        F"{outputfile}_machine_collsions.png")
    Collisions.write_to_png(path) 
    demoFactory.printTime("PNG schreiben")

    toutput = demoFactory.drawPositions(drawMaterialflow = True, drawColors = False, drawMachineCenter = False, drawOrigin = False,  highlight=1)
    toutput = demoFactory.drawCollisions(surfaceIn = toutput, drawColors = False)
    toutput = demoFactory.drawPositions(drawMaterialflow = True, drawMachines = False, drawColors = False, drawMachineCenter = True, drawOrigin = False)
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
        "..",
        "..",
        "Output", 
        F"{outputfile}test.png")
    toutput.write_to_png(path) 
    demoFactory.printTime("PNG schreiben")

    ##Rate current Layout
    demoFactory.evaluate()

    print(f"Total runtime: {round((time() - demoFactory.timezero) * 1000, 2)}")

    
if __name__ == "__main__":
    from factorySim.factoryObject import FactoryObject 
    main()
else:
    from factorySim.factoryObject import FactoryObject
    