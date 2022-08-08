# %%
import numpy as np
import matplotlib.pyplot as plt
from shapely.geometry import Point, MultiPoint, MultiPolygon, MultiLineString, GeometryCollection, box, shape
from shapely.affinity import translate, rotate
from shapely.strtree import STRtree
from shapely.ops import split,  voronoi_diagram,  unary_union, triangulate, nearest_points
import descartes
import networkx as nx
import pickle
import ezdxf
from ezdxf.addons import geo
from tqdm import tqdm

from helpers import pruneAlongPath


import time
# %%
SAVEPLOT = False
SAVEFORMAT = "png"
DETAILPLOT = False
PLOT = True
TIMING = True
LOADDATA = False
LOADDXF = False
ITERATIONS = 1

# savedata = { "bounding_box": bb, "machines": multi }
# pickle.dump( savedata, open( "FigureFactory.p", "wb" ) )


#%% Single Machines
WIDTH = 8
HEIGHT = 8
MAXSHAPEWIDTH = 4
MAXSHAPEHEIGHT = 5
AMOUNTRECT = 2
AMOUNTPOLY = 1
MAXCORNERS = 3

#%% Full Layout
WIDTH = 32
HEIGHT = 32
MAXSHAPEWIDTH = 4
MAXSHAPEHEIGHT = 4
AMOUNTRECT = 25
AMOUNTPOLY = 5
MAXCORNERS = 3


#%%
MINDEADEND_LENGTH = 2.0 # If Deadends are shorter than this, they are deleted
MINPATHWIDTH = 1.0  # Minimum Width of a Road to keep
BOUNDARYSPACING = 2.0  # Spacing of Points used as Voronoi Kernels
#%% Create Layout -----------------------------------------------------------------------------------------------------------------
for i in tqdm(range(ITERATIONS)):

    starttime = time.perf_counter()
    totaltime = starttime

    rng = np.random.default_rng()
    bb = box(0,0,WIDTH,HEIGHT)

    lowerLeftCornersRect = rng.integers([0,0], [WIDTH - MAXSHAPEWIDTH, HEIGHT - MAXSHAPEHEIGHT], size=[AMOUNTRECT,2], endpoint=True)
    lowerLeftCornersPoly = rng.integers([0,0], [WIDTH - MAXSHAPEWIDTH, HEIGHT - MAXSHAPEWIDTH], size=[AMOUNTPOLY,2], endpoint=True)

    polygons = []
    #Create Recangles
    for x,y in lowerLeftCornersRect:
        singlePoly = box(x,y,x + rng.integers(1, MAXSHAPEWIDTH+1), y + rng.integers(1, MAXSHAPEHEIGHT+1))
        singlePoly= rotate(singlePoly, rng.choice([0,90,180,270]))  
        polygons.append(singlePoly)

    #Create Convex Polygons
    for x,y in lowerLeftCornersPoly: 
        corners = []
        corners.append([x,y]) # First Corner
        for _ in range(rng.integers(2,MAXCORNERS+1)):
            corners.append([x + rng.integers(0, MAXSHAPEWIDTH+1), y + rng.integers(0, MAXSHAPEWIDTH+1)])

        singlePoly = MultiPoint(corners).minimum_rotated_rectangle
        singlePoly= rotate(singlePoly, rng.integers(0,361))  
        #Filter Linestrings
        if singlePoly.geom_type ==  'Polygon':
        #Filter small Objects
            if singlePoly.area > MAXSHAPEWIDTH*MAXSHAPEWIDTH*0.05:
                polygons.append(singlePoly)
        
    multi = unary_union(MultiPolygon(polygons))

    if LOADDATA:
        loaddata = pickle.load( open( "FigureFactory.p", "rb" ) )
        bb = loaddata["bounding_box"]
        multi = loaddata["machines"]

    if LOADDXF:
        doc = ezdxf.readfile("Test.dxf")
        geo_proxy = geo.proxy(doc.modelspace())
        multi = shape(geo_proxy)


    walkableArea = bb.difference(multi)
    if walkableArea.geom_type ==  'MultiPolygon':
        walkableArea = walkableArea.geoms[0]

    nextTime = time.perf_counter()
    if TIMING: print(f"Factory generation {nextTime - starttime}")
    starttime = nextTime

    # %% Create Voronoi -----------------------------------------------------------------------------------------------------------------

    #Points around boundary
    distances = np.arange(0,  bb.boundary.length, BOUNDARYSPACING)
    points = [ bb.boundary.interpolate(distance) for distance in distances]
    
    #Points on Machines
    distances = np.arange(0,  multi.boundary.length, BOUNDARYSPACING)
    points.extend([ multi.boundary.interpolate(distance) for distance in distances])
    bb_points = unary_union(points) 

    nextTime = time.perf_counter()
    if TIMING: print(f"Boundary generation {nextTime - starttime}")
    starttime = nextTime

    voronoiBase = GeometryCollection([walkableArea, bb_points])
    voronoiArea = voronoi_diagram(voronoiBase, edges=True)

    nextTime = time.perf_counter()
    if TIMING: print(f"Voronoi {nextTime - starttime}")
    starttime = nextTime

    route_lines = []
    lines_touching_machines = []
    lines_to_machines = []

    for line in voronoiArea.geoms[0].geoms:
        #find routes close to machines
        if  multi.intersects(line) or bb.crosses(line): 
            lines_touching_machines.append(line)
        #rest are main routes and dead ends
        else:
            route_lines.append(line)
        

    nextTime = time.perf_counter()
    if TIMING: print(f"Find Routes {nextTime - starttime}")
    starttime = nextTime


    #Split lines with machine objects#
    try:
        sresult = split(MultiLineString(lines_touching_machines), multi)
    except:
        print("Split Error")
        continue

    nextTime = time.perf_counter()
    if TIMING: print(f"Split {nextTime - starttime}")
    starttime = nextTime


    #Remove Geometries that are inside machines
    for line in sresult.geoms:
        if  not (multi.covers(line) and (not multi.disjoint(line) ) or multi.crosses(line)):
            lines_to_machines.append(line)

    nextTime = time.perf_counter()
    if TIMING: print(f"Line Filtering {nextTime - starttime}")
    starttime = nextTime

    # Find closest points in voronoi cells
    hitpoints = points + list(MultiPoint(walkableArea.exterior.coords).geoms)
    hit_tree = STRtree(hitpoints)


    # Create Graph -----------------------------------------------------------------------------------------------------------------
    G = nx.Graph()

    memory = None
    memomry_distance = None

    for line in route_lines:

        first = line.boundary.geoms[0]
        firstTuple = (first.x, first.y)
        first_str = str(firstTuple)
        #find closest next point in boundary for path width calculation
        if memory == first:
            first_distance = memomry_distance
        else:
            nearest_point_first = hit_tree.nearest_geom(first)
            first_distance = first.distance(nearest_point_first)

        second = line.boundary.geoms[1]
        secondTuple = (second.x, second.y)
        second_str = str(secondTuple)
        #find closest next point in boundary for path width calculation
        nearest_point_second = hit_tree.nearest_geom(second)
        second_distance = second.distance(nearest_point_second)
        memory, memomry_distance = second, second_distance

        #edge width is minimum path width of the nodes making up the edge
        smallestPathwidth = min(first_distance, second_distance)


    #This is replaced by the version below. Delete Line Filtering below as well 
        G.add_node(first_str, pos=firstTuple, pathwidth=smallestPathwidth)
        G.add_node(second_str, pos=secondTuple, pathwidth=smallestPathwidth)
        G.add_edge(first_str, second_str, weight=first.distance(second), pathwidth=smallestPathwidth)


    #For later --------------------------
        # if smallestPathwidth < MINPATHWIDTH:
        #     continue
        # else:
        #     G.add_node(first_str, pos=firstTuple, pathwidth=smallestPathwidth)
        #     G.add_node(second_str, pos=secondTuple, pathwidth=smallestPathwidth)
        #     G.add_edge(first_str, second_str, weight=first.distance(second), pathwidth=smallestPathwidth)



    nextTime = time.perf_counter()
    if TIMING: print(f"Network generation {nextTime - starttime}")
    starttime = nextTime
    # Filter  Graph -----------------------------------------------------------------------------------------------------------------
    """Cleans road network created with voronoi method by 
    - removing elements that are narrower than min_pathwidth
    - removing any dangelength parts that might have been cut off
    - removing all dead end that are shorter than min_length

    """

    narrowPaths = [(n1, n2) for n1, n2, w in G.edges(data="pathwidth") if w < MINPATHWIDTH]
    F = G.copy()
    F.remove_edges_from(narrowPaths)

    #Find largest connected component to filter out "loose" parts
    Fcc = sorted(nx.connected_components(F), key=len, reverse=True)

    #print(f"Connected components ratio: {len(Fcc[0])/len(Fcc[1])}", )
    #if len(Fcc[0])/len(Fcc[1]) < 10: continue

 
    F = F.subgraph(Fcc[0]).copy()

    #find crossroads
    old_crossroads = [node for node, degree in F.degree() if degree >= 3]
    #Set isCrossroads attribute on cross road nodes

    nx.set_node_attributes(F, dict.fromkeys(old_crossroads, True), 'isCrossroads')
    #find deadends
    old_endpoints = [node for node, degree in F.degree() if degree == 1]


    shortDeadEnds = pruneAlongPath(F, starts=old_endpoints, ends=old_crossroads, min_length=MINDEADEND_LENGTH)

    F.remove_nodes_from(shortDeadEnds)
    endpoints = [node for node, degree in F.degree() if degree == 1]
    crossroads = [node for node, degree in F.degree() if degree >= 3]

# Prune unused dead ends
    pos=nx.get_node_attributes(G,'pos')

    repPoints = [poly.representative_point() for poly in multi.geoms]
    #Create Positions lists for nodes, since we need to querry shapley for shortest distance
    endpoint_pos = [pos[endpoint] for endpoint in endpoints ]
    crossroad_pos = [pos[crossroad] for crossroad in crossroads]
    total = endpoint_pos + crossroad_pos

    endpoints_to_prune = endpoints.copy()

    for point in repPoints:
        hit = nearest_points(point, MultiPoint(total))[1]
        key = str((hit.x, hit.y))
        if key in endpoints_to_prune: endpoints_to_prune.remove(key)

    nodes_to_prune = pruneAlongPath(F, starts=endpoints_to_prune, ends=crossroads, min_length=10)

    E = F.copy()
    E.remove_nodes_from(nodes_to_prune)

    endpoints = [node for node, degree in E.degree() if degree == 1]
    crossroads = [node for node, degree in E.degree() if degree >= 3]

    nextTime = time.perf_counter()
    if TIMING: print(f"Network Filtering {nextTime - starttime}")
    starttime = nextTime


    # Simplyfy  Graph ------------------------------------------------------------------------------------------------------------

    H = E.copy()


    # Select all nodes with only 2 neighbors
    nodes_to_remove = [n for n in H.nodes if len(list(H.neighbors(n))) == 2]

    # For each of those nodes
    for node in nodes_to_remove:
        
        # Get the two neighbors
        neighbors = list(H.neighbors(node))
        #if len is not 2 we found a loop 
        if len(neighbors) == 2:
            total_weight = H[neighbors[0]][node]["weight"] + H[node][neighbors[1]]["weight"]
            pathwidth = min(H[neighbors[0]][node]["pathwidth"], H[node][neighbors[1]]["pathwidth"])
            max_pathwidth = max(H[neighbors[0]][node]["pathwidth"], H[node][neighbors[1]]["pathwidth"])
            H.add_edge(*neighbors, weight=total_weight, pathwidth=pathwidth, max_pathwidth=max_pathwidth)
        # And delete the node
        H.remove_node(node)
      
    nextTime = time.perf_counter()

    if TIMING: 
        print(f"Network Simplification {nextTime - starttime}")
        print(f"Algorithm Total: {nextTime - totaltime}")
        
    starttime = nextTime

    # Create Machine Colors
    machine_colors = []

    if multi.geom_type ==  'Polygon':
        machine_colors.append(rng.random(size=3))
    else:
        machine_colors = rng.random(size=(len(multi.geoms),3))

    
if PLOT:
        # %% Filtered_Lines Plot -----------------------------------------------------------------------------------------------------------------
        if DETAILPLOT:

            
            fig, ax = plt.subplots(1,figsize=(16, 16))
            plt.xlim(0,WIDTH)
            plt.ylim(0,HEIGHT)
            plt.autoscale(False)


            if multi.geom_type ==  'Polygon':
                ax.add_patch(descartes.PolygonPatch(multi, fc=machine_colors[0], ec='#000000', alpha=0.5))
            else:
                for j, poly in enumerate(multi.geoms):
                    ax.add_patch(descartes.PolygonPatch(poly, fc=machine_colors[j], ec='#000000', alpha=0.5))
            for line in route_lines:
                ax.plot(line.xy[0], line.xy[1], color='dimgray', linewidth=3)
            for line in lines_touching_machines:
                ax.plot(line.xy[0], line.xy[1], color='green', alpha=0.5)
            for line in lines_to_machines:
                ax.plot(line.xy[0], line.xy[1], color='red', alpha=0.9)

            # for point in bb_points:
            #     ax.scatter(point.xy[0], point.xy[1], color='red')
            #ax.add_patch(descartes.PolygonPatch(allEdges, fc='blue', ec='#000000', alpha=0.5))  
            if SAVEPLOT: plt.savefig(f"{i+1}_1_Filtered_Lines.{SAVEFORMAT}", format=SAVEFORMAT)
            plt.show()

        # %% Pathwidth_Calculation Plot -----------------------------------------------------------------------------------------------------------------
        if DETAILPLOT:
            fig, ax = plt.subplots(1,figsize=(16, 16))
            plt.xlim(0,WIDTH)
            plt.ylim(0,HEIGHT)
            plt.autoscale(False)


            if multi.geom_type ==  'Polygon':
                ax.add_patch(descartes.PolygonPatch(multi, fc=machine_colors[0], ec='#000000', alpha=0.5))
            else:
                for j, poly in enumerate(multi.geoms):
                    ax.add_patch(descartes.PolygonPatch(poly, fc=machine_colors[j], ec='#000000', alpha=0.5))

            # for line in voronoiArea_:
            #     ax.plot(line.xy[0], line.xy[1], color='green', alpha=0.5)
            for line in voronoiArea.geoms[0].geoms:
                ax.plot(line.xy[0], line.xy[1], color='red', alpha=0.0)



            for point in hitpoints:
                ax.scatter(point.x, point.y, color='red')

            for line in route_lines:
                ax.plot(line.xy[0], line.xy[1], color='black')
                # Plot Circle for every line Endpoint, since Startpoint is likely connected to other line segment
                point = line.boundary.geoms[0]
                nearest_point = hit_tree.nearest_geom(point)
                #ax.plot([point.x, nearest_point.x], [point.y, nearest_point.y], color='green', alpha=1)
                ax.add_patch(plt.Circle((point.x, point.y), point.distance(nearest_point), color='blue', fill=False, alpha=0.6))
                #ax.add_patch(descartes.PolygonPatch(line.buffer(1), fc="black", ec='#000000', alpha=0.5))


            if SAVEPLOT: plt.savefig(f"{i+1}_2_Pathwidth_Calculation.{SAVEFORMAT}", format=SAVEFORMAT)
            plt.show()

        # %% Filtering Plot -----------------------------------------------------------------------------------------------------------------

        fig, ax = plt.subplots(1, figsize=(16, 16))
        ax.set_xlim(0,WIDTH)
        ax.set_ylim(0,HEIGHT)
        plt.autoscale(False)

        if multi.geom_type ==  'Polygon':
            ax.add_patch(descartes.PolygonPatch(multi, fc=machine_colors[0], ec='#000000', alpha=0.5))
        else:
            for j, poly in enumerate(multi.geoms):
                ax.add_patch(descartes.PolygonPatch(poly, fc=machine_colors[j], ec='#000000', alpha=0.5))

        pathwidth = np.array(list((nx.get_edge_attributes(G,'pathwidth').values())))

        nx.draw_networkx_edges(G, pos=pos, ax=ax, edge_color="silver", width=pathwidth * 50, alpha=0.6)
        nx.draw_networkx_edges(G, pos=pos, ax=ax, edge_color="red", width=2, alpha=1)
        nx.draw_networkx_edges(F, pos=pos, ax=ax, edge_color="lime", width=2, alpha=1)
        nx.draw_networkx_edges(E, pos=pos, ax=ax, edge_color="dimgrey", width=5, alpha=1)
        nx.draw_networkx_edges(G, pos=pos, ax=ax, edgelist=narrowPaths, edge_color="blue", width=2, alpha=1)


        nx.draw_networkx_nodes(G, pos=pos, ax=ax, nodelist=shortDeadEnds, node_size=80, node_color='white', alpha=0.6, linewidths=4, edgecolors='green')
        nx.draw_networkx_nodes(G, pos=pos, ax=ax, nodelist=old_endpoints, node_size=150, node_color='green')
        nx.draw_networkx_nodes(G, pos=pos, ax=ax, nodelist=old_crossroads, node_size=150, node_color='white', alpha=0.6, linewidths=4, edgecolors='red')

        if SAVEPLOT: plt.savefig(f"{i+1}_3_Pruning.{SAVEFORMAT}", format=SAVEFORMAT)
        
        plt.show()

        # %% Clean Plot -----------------------------------------------------------------------------------------------------------------

        fig, ax = plt.subplots(1, figsize=(16, 16))

        ax.set_xlim(0,WIDTH)
        ax.set_ylim(0,HEIGHT)
        plt.autoscale(False)

        if multi.geom_type ==  'Polygon':
            ax.add_patch(descartes.PolygonPatch(multi, fc=machine_colors[0], ec='#000000', alpha=0.5))
        else:
            for j, poly in enumerate(multi.geoms):
                ax.add_patch(descartes.PolygonPatch(poly, fc=machine_colors[j], ec='#000000', alpha=0.5))


        weights = np.array(list((nx.get_edge_attributes(E,'weight').values())))
        pathwidth = np.array(list((nx.get_edge_attributes(E,'pathwidth').values())))

        #nx.draw_networkx_nodes(F, pos=pos, ax=ax, node_size=20, node_color='black', alpha=0.5)
        nx.draw_networkx_nodes(E, pos=pos, ax=ax, nodelist=crossroads, node_size=120, node_color='red')
        nx.draw_networkx_nodes(E, pos=pos, ax=ax, nodelist=endpoints, node_size=120, node_color='blue')
        nx.draw_networkx_edges(E, pos=pos, ax=ax, width=pathwidth * 9, edge_color="dimgray", alpha=0.8)
        nx.draw_networkx_edges(E, pos=pos, ax=ax, width=3, edge_color="black", alpha=0.5)

        if SAVEPLOT: plt.savefig(f"{i+1}_4_Clean.{SAVEFORMAT}", format=SAVEFORMAT)
        
        plt.show()




        # %% Simplification Plot -----------------------------------------------------------------------------------------------------------------


        fig, ax = plt.subplots(1,figsize=(16, 16))
        plt.xlim(0,WIDTH)
        plt.ylim(0,HEIGHT)
        plt.autoscale(False)


        if multi.geom_type ==  'Polygon':
            ax.add_patch(descartes.PolygonPatch(multi, fc=machine_colors[0], ec='#000000', alpha=0.5))
        else:
            for j, poly in enumerate(multi.geoms):
                ax.add_patch(descartes.PolygonPatch(poly, fc=machine_colors[j], ec='#000000', alpha=0.5))


        min_pathwidth = np.array(list((nx.get_edge_attributes(H,'pathwidth').values())))
        max_pathwidth = np.array(list((nx.get_edge_attributes(H,'max_pathwidth').values())))
        print(f"max {len(max_pathwidth)}, min {len(min_pathwidth)}")

        nx.draw_networkx_nodes(E, pos=pos, ax=ax, node_size=20, node_color='black')
        nx.draw_networkx_nodes(H, pos=pos, ax=ax, node_size=120, node_color='red')
        nx.draw_networkx_edges(H, pos=pos, ax=ax, width=max_pathwidth * 9, edge_color="grey", alpha=0.8)
        nx.draw_networkx_edges(H, pos=pos, ax=ax, width=min_pathwidth * 9, edge_color="black", alpha=0.7)
        nx.draw_networkx_edges(E, pos=pos, ax=ax, edge_color="dimgray", alpha=0.5)


        if SAVEPLOT: plt.savefig(f"{i+1}_5_Simplification.{SAVEFORMAT}", format=SAVEFORMAT)
        plt.show()


        nextTime = time.perf_counter()
        if TIMING: print(f"Plotting {nextTime - starttime}")

        print(f"Mean Road Dimension Variability: {np.mean(min_pathwidth/max_pathwidth)}")



# 2 - Überschneidungsfreiheit	        Materialflussschnittpunkte
# 3 - Stetigkeit	                    Richtungswechsel im Materialfluss



# 	                                    Verwinkelung
# 	                                    Vorhandensein eindeutiger Wegachsen
# 	                                    Wegeeffizienz
# 6 - Zugänglichkeit	                Abdeckung Wegenetz
# 	                                    Kontaktflächen Wegenetz
# 7 - Flächennutzungsgrad	            genutzte Fabrikfläche (ohne zusammenhängende Freifläche)
# 1 - Skalierbarkeit 	                Ausdehnung der größten verfügbaren Freifläche
# 2 - Medienverfügbarkeit	            Möglichkeit des Anschlusses von Maschinen an Prozessmedien (z.B. Wasser, Druckluft)
# 1 - Beleuchtung	                    Erfüllung der Arbeitsplatzanforderungen
# 2 - Ruhe	                            Erfüllung der Arbeitsplatzanforderungen
# 3 - Erschütterungsfreiheit	        Erfüllung der Arbeitsplatzanforderungen
# 4 - Sauberkeit	                    Erfüllung der Arbeitsplatzanforderungen
# 5 - Temperatur	                    Erfüllung der Arbeitsplatzanforderungen



# Erledigt =================================================================

# 1 - Materialflusslänge	            Entfernung (direkt)
# 	                                    Entfernung (wegorientiert)
# 4 - Intensität	                    Anzahl der Transporte
# 5 - Wegekonzept	                    Auslegung Wegbreite
# 	                                    Sackgassen



#%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

fig, ax = plt.subplots(1,figsize=(16, 16))
plt.xlim(0,WIDTH)
plt.ylim(0,HEIGHT)
plt.autoscale(False)



ax.add_patch(descartes.PolygonPatch(walkableArea, alpha=0.5))
triangles = triangulate(walkableArea)

# for tri in triangles:
#     ax.add_patch(descartes.PolygonPatch(tri, alpha=0.5))

nx.draw_networkx_edges(F, pos=pos, ax=ax, edge_color="grey", width=4)
nx.draw_networkx_edges(E, pos=pos, ax=ax, edge_color="red", width=5)
repPoints = [poly.representative_point() for poly in multi.geoms]
endpoint_pos = [pos[endpoint] for endpoint in endpoints ]
crossroad_pos = [pos[crossroad] for crossroad in crossroads]
total = endpoint_pos + crossroad_pos

endpoints_to_prune = endpoints.copy()



for point in repPoints:
    ax.plot(point.x, point.y, 'o', color='green', ms=10)
    hit = nearest_points(point, MultiPoint(total))[1]
    ax.plot([point.x, hit.x],[ point.y, hit.y], color=rng.random(size=3),linewidth=3)
    key = str((hit.x, hit.y))
    if key in endpoints_to_prune: endpoints_to_prune.remove(key)



plt.show()


# %%
print("Fertsch")



